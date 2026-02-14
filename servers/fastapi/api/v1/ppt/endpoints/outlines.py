import asyncio
import json
import math
import traceback
import uuid
import dirtyjson
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from models.presentation_outline_model import PresentationOutlineModel
from models.sql.presentation import PresentationModel
from models.sse_response import (
    SSECompleteResponse,
    SSEErrorResponse,
    SSEResponse,
    SSEStatusResponse,
)
from services.temp_file_service import TEMP_FILE_SERVICE
from services.database import get_async_session
from services.documents_loader import DocumentsLoader
from services.agentic_research_service import AgenticResearchService
from utils.llm_calls.generate_presentation_outlines import generate_ppt_outline
from utils.ppt_utils import get_presentation_title_from_outlines

OUTLINES_ROUTER = APIRouter(prefix="/outlines", tags=["Outlines"])


@OUTLINES_ROUTER.get("/stream/{id}")
async def stream_outlines(
    id: uuid.UUID, sql_session: AsyncSession = Depends(get_async_session)
):
    presentation = await sql_session.get(PresentationModel, id)

    if not presentation:
        raise HTTPException(status_code=404, detail="Presentation not found")

    temp_dir = TEMP_FILE_SERVICE.create_temp_dir()

    async def inner():
        yield SSEStatusResponse(
            status="Generating presentation outlines..."
        ).to_string()

        # --------------------------------------------
        # LOAD UPLOADED FILE CONTEXT
        # --------------------------------------------
        additional_context = ""

        if presentation.file_paths:
            yield SSEStatusResponse(
                status="Loading uploaded documents..."
            ).to_string()

            documents_loader = DocumentsLoader(file_paths=presentation.file_paths)
            await documents_loader.load_documents(temp_dir)
            documents = documents_loader.documents

            if documents:
                additional_context = "\n\n".join(documents)

        # --------------------------------------------
        # AGENTIC RESEARCH INJECTION
        # --------------------------------------------
        research_context = ""

        if presentation.web_search:
            yield SSEStatusResponse(
                status="Running agentic research (web + wikipedia + archive)..."
            ).to_string()

            try:
                research_service = AgenticResearchService()
                research_context = await research_service.run(
                    presentation.content
                )

                if research_context:
                    yield SSEStatusResponse(
                        status="Research completed. Enhancing outline generation..."
                    ).to_string()
                else:
                    yield SSEStatusResponse(
                        status="No external research found. Continuing..."
                    ).to_string()

            except Exception as e:
                print(f"[Research Error] {str(e)}")
                yield SSEStatusResponse(
                    status="Research failed. Continuing without external context."
                ).to_string()

        # --------------------------------------------
        # MERGE CONTEXT
        # --------------------------------------------
        final_context = additional_context

        if research_context:
            final_context = (
                (additional_context + "\n\n" if additional_context else "")
                + "External Research Context:\n"
                + research_context
            )

        # --------------------------------------------
        # CALCULATE SLIDES TO GENERATE
        # --------------------------------------------
        n_slides_to_generate = presentation.n_slides

        if presentation.include_table_of_contents:
            needed_toc_count = math.ceil((presentation.n_slides - 1) / 10)
            n_slides_to_generate -= math.ceil(
                (presentation.n_slides - needed_toc_count) / 10
            )

        presentation_outlines_text = ""

        # --------------------------------------------
        # GENERATE OUTLINES (STREAMING)
        # --------------------------------------------
        async for chunk in generate_ppt_outline(
            presentation.content,
            n_slides_to_generate,
            presentation.language,
            final_context,
            presentation.tone,
            presentation.verbosity,
            presentation.instructions,
            presentation.include_title_slide,
            presentation.web_search,
        ):
            await asyncio.sleep(0)

            if isinstance(chunk, HTTPException):
                yield SSEErrorResponse(detail=chunk.detail).to_string()
                return

            yield SSEResponse(
                event="response",
                data=json.dumps({"type": "chunk", "chunk": chunk}),
            ).to_string()

            presentation_outlines_text += chunk

        # --------------------------------------------
        # PARSE JSON OUTPUT
        # --------------------------------------------
        try:
            presentation_outlines_json = dict(
                dirtyjson.loads(presentation_outlines_text)
            )
        except Exception as e:
            traceback.print_exc()
            yield SSEErrorResponse(
                detail=f"Failed to generate presentation outlines. Please try again. {str(e)}",
            ).to_string()
            return

        presentation_outlines = PresentationOutlineModel(
            **presentation_outlines_json
        )

        presentation_outlines.slides = presentation_outlines.slides[
            :n_slides_to_generate
        ]

        # --------------------------------------------
        # SAVE TO DATABASE
        # --------------------------------------------
        presentation.outlines = presentation_outlines.model_dump()
        presentation.title = get_presentation_title_from_outlines(
            presentation_outlines
        )

        sql_session.add(presentation)
        await sql_session.commit()

        yield SSECompleteResponse(
            key="presentation",
            value=presentation.model_dump(mode="json"),
        ).to_string()

    return StreamingResponse(inner(), media_type="text/event-stream")
