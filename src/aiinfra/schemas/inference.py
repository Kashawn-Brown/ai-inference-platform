"""Live inference request/response schemas (brief Section 3).

The v1 surface is deliberately narrow: prompt + generation params in, model
output + usage + timing out. No per-request `model` override and no caller
`metadata` field — both would drift toward multi-model/provider behavior, which
is out of scope. The served model is fixed by config in v1.
"""

from pydantic import BaseModel, Field


class InferenceRequest(BaseModel):
    prompt: str = Field(min_length=1, description="Prompt text to send to the model.")
    max_tokens: int = Field(
        default=512,
        ge=1,
        le=8192,
        description="Maximum tokens to generate. Upper bound guards against "
        "abuse; the deployment's vLLM max-model-len may be lower.",
    )
    temperature: float = Field(
        default=0.7,
        ge=0.0,
        le=2.0,
        description="Sampling temperature; 0.0 is greedy.",
    )


class Usage(BaseModel):
    prompt_tokens: int
    completion_tokens: int


class InferenceResponse(BaseModel):
    request_id: str = Field(description="Correlation ID for this request.")
    model: str = Field(description="Model that produced the output.")
    output: str
    usage: Usage
    latency_ms: int = Field(
        description="Server-side wall-clock latency, gateway-measured."
    )
