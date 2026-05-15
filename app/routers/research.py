import asyncio
import logging
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.core.gemini_client import gemini_client
from app.core.stream import format_sse
from app.models.gemini import DeepResearchRequest, InteractionRequest

logger = logging.getLogger(__name__)

router = APIRouter()


async def _plan_research(query: str, model: str, language: str) -> dict:
    """Generate sub-questions and outline for the research query."""
    prompt = (
        f"You are a research assistant. Break down the following query into 3-5 specific "
        f"sub-questions that need to be answered to thoroughly research this topic. "
        f"Also provide a brief outline. Respond in {language}.\n\n"
        f"Query: {query}\n\n"
        f"Format your response as:\n"
        f"SUB-QUESTIONS:\n1. [question]\n2. [question]\n...\n\n"
        f"OUTLINE:\n[brief outline]"
    )

    result = await gemini_client.generate(prompt, model)
    return result


async def _research_question(sub_question: str, model: str, language: str) -> dict:
    """Research a single sub-question."""
    prompt = (
        f"Research the following question thoroughly: '{sub_question}'. "
        f"Provide detailed findings with sources where possible. "
        f"Respond in {language}."
    )

    result = await gemini_client.generate(prompt, model)
    return result


async def _synthesize_report(query: str, all_findings: list[str], model: str, language: str) -> dict:
    """Synthesize all research findings into a comprehensive report."""
    findings_text = "\n\n---\n\n".join(
        f"Finding {i+1}:\n{finding}" for i, finding in enumerate(all_findings)
    )

    prompt = (
        f"Based on the following research findings, write a comprehensive report "
        f"answering the original query: '{query}'\n\n"
        f"{findings_text}\n\n"
        f"Provide a well-structured report with citations. Respond in {language}."
    )

    result = await gemini_client.generate(prompt, model)
    return result


def _extract_sub_questions(plan_text: str) -> list[str]:
    """Extract sub-questions from the planning response."""
    lines = plan_text.split("\n")
    questions = []
    in_questions_section = False

    for line in lines:
        line = line.strip()
        if "SUB-QUESTIONS:" in line.upper():
            in_questions_section = True
            continue
        if "OUTLINE:" in line.upper():
            in_questions_section = False
            continue

        if in_questions_section and line:
            # Remove numbering like "1. ", "2. ", etc.
            cleaned = line.lstrip("0123456789.-) ").strip()
            if cleaned:
                questions.append(cleaned)

    # Fallback: if no questions found, return a generic one
    if not questions:
        questions = ["Provide comprehensive information about this topic."]

    return questions


async def _perform_deep_research(
    query: str, model: str, language: str, max_sources: int
) -> dict:
    """Perform complete deep research workflow."""
    task_id = str(uuid4())

    # Step 1: Plan
    logger.info(f"[{task_id}] Planning research for: {query}")
    plan_result = await _plan_research(query, model, language)
    plan_text = plan_result.get("text", "")

    # Extract sub-questions
    sub_questions = _extract_sub_questions(plan_text)
    # Limit to max_sources
    sub_questions = sub_questions[:max_sources]

    logger.info(f"[{task_id}] Generated {len(sub_questions)} sub-questions")

    # Step 2: Research each sub-question
    findings = []
    for i, sub_q in enumerate(sub_questions):
        logger.info(f"[{task_id}] Researching sub-question {i+1}/{len(sub_questions)}")
        research_result = await _research_question(sub_q, model, language)
        findings.append(research_result.get("text", ""))

    # Step 3: Synthesize
    logger.info(f"[{task_id}] Synthesizing final report")
    synthesis_result = await _synthesize_report(query, findings, model, language)

    return {
        "task_id": task_id,
        "query": query,
        "plan": plan_text,
        "sub_questions": sub_questions,
        "findings": findings,
        "report": synthesis_result.get("text", ""),
        "conversation_id": synthesis_result.get("conversation_id", ""),
    }


@router.post("/gemini/v1beta/deepresearch")
async def deep_research(request: DeepResearchRequest):
    """
    Perform synchronous deep research.

    Returns the complete research report after all steps are finished.
    """
    if not gemini_client.is_healthy:
        raise HTTPException(status_code=503, detail="Gemini client not ready")

    # Use first available model if not specified
    model = request.model
    if not model:
        if not gemini_client.models:
            raise HTTPException(status_code=503, detail="No models available")
        model = gemini_client.models[0]

    try:
        result = await _perform_deep_research(
            request.query, model, request.language, request.max_s        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"Deep research failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Research failed")


@router.post("/gemini/v1beta/deepresearch/stream")
async def deep_research_stream(request: DeepResearchRequest):
    """
    Perform deep research with SSE streaming progress updates.

    Emits events:
    - progress: {"type": "progress", "percentage": 0-100, "message": "..."}
    - step: {"type": "step", "step": "plan|research|synthesize", "data": {...}}
    - result: {"type": "result", "report": "...", "task_id": "..."}
    - done: {"type": "done"}
    """
    if not gemini_client.is_healthy:
        raise HTTPException(status_code=503, detail="Gemini client not ready")

    model = request.model
    if not model:
        if not gemini_client.models:
            raise HTTPException(status_code=503, detail="No models available")
        model = gemini_client.models[0]

    async def event_generator():
        task_id = str(uuid4())

        try:
            # Step 1: Plan (0-20%)
            yield format_sse({
                "type": "progress",
                "percentage": 0,
                "message": "Planning research..."
            })

            plan_result = await _plan_research(request.query, model, request.language)
            plan_text = plan_result.get("text", "")
            sub_questions = _extract_sub_questions(plan_text)
            sub_questions = sub_questions[:request.max_sources]

            yield format_sse({
                "type": "step",
                "step": "plan",
                "data": {
                    "plan": plan_text,
                    "sub_questions": sub_questions,
                    "total_questions": len(sub_questions)
                }
            })

            yield format_sse({
                "type": "progress",
                "percentage": 20,
                "message": f"Generated {len(sub_questions)} research questions"
            })

            # Step 2: Research (20-80%)
            findings = []
            total_questions = len(sub_questions)

            for i, sub_q in enumerate(sub_questions):
                progress = 20 + int((i / total_questions) * 60)
                yield format_sse({
                    "type": "progress",
                    "percentage": progress,
                    "message": f"Researching question {i+1}/{total_questions}..."
                })

                research_result = await _research_question(sub_q, model, request.language)
                finding_text = research_result.get("text", "")
                findings.append(finding_text)

                yield format_sse({
                    "type": "step",
                    "step": "research",
                    "data": {
                        "question_index": i,
                        "question": sub_q,
                        "finding": finding_text
                    }
                })

            yield format_sse({
                "type": "progress",
                "percentage": 80,
                "message": "Synthesizing final report..."
            })

            # Step 3: Synthesize (80-100%)
            synthesis_result = await _synthesize_report(
                request.query, findings, model, request.language
            )
            report = synthesis_result.get("text", "")

            yield format_sse({
                "type": "step",
                "step": "synthesize",
                "data": {
                    "report": report
                }
            })

            yield format_sse({
                "type": "progress",
                "percentage": 100,
                "message": "Research complete"
            })

            # Final result
            yield format_sse({
                "type": "result",
                "task_id": task_id,
                "query": request.query,
                "report": report,
                "conversation_id": synthesis_result.get("conversation_id", "")
            })

            yield format_sse({"type": "done"})

        except Exception as e:
            logger.error(f"Stream research failed: {e}", exc_info=True)
            yield format_sse({
                "type": "error",
                "message": str(e)
            })

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@router.post("/gemini/v1beta/deepresearch/interact")
async def deep_research_interact(request: InteractionRequest):
    """
    Interactive deep research endpoint.

    Allows follow-up questions and iterative research.
    Can return streaming or synchronous responses.
    """
    if not gemini_client.is_healthy:
        raise HTTPException(status_code=503, detail="Gemini client not ready")

    if not gemini_client.models:
        raise HTTPException(status_code=503, detail="No models available")

    model = gemini_client.models[0]

    # For interactive mode, treat input as a direct research query
    prompt = (
        f"You are a research assistant. Answer the following question thoroughly "
        f"with detailed information and sources where possible. "
        f"Respond in {request.language}.\n\n"
        f"Question: {request.input}"
    )

    if request.stream:
        # Return streaming response
        async def event_generator():
            try:
                result = await gemini_client.generate(prompt, model)
                text = result.get("text", "")

                # Stream the response word by word
                words = text.split()
                total_words = len(words)

                for i, word in enumerate(words):
                    chunk = word if i == total_words - 1 else word + " "
                    yield format_sse({
                        "type": "chunk",
                        "text": chunk
                    })
                    await asyncio.sleep(0.03)

                yield format_sse({
                    "type": "done",
                    "conversation_id": result.get("conversation_id", "")
                })

            except Exception as e:
                logger.error(f"Interactive research failed: {e}", exc_info=True)
                yield format_sse({
                    "type": "error",
                    "message": str(e)
                })

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            }
        )
    else:
        # Return synchronous response
        try:
            result = await gemini_client.generate(prompt, model)
            return {
                "response": result.get("text", ""),
                "conversation_id": result.get("conversation_id", "")
            }
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except RuntimeError as e:
            raise HTTPException(status_code=503, detail=str(e))
        except Exception as e:
            logger.error(f"Interactive research failed: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="Research failed")
