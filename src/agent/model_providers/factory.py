import os

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_google_vertexai.model_garden import ChatAnthropicVertex
from langchain_openai import AzureChatOpenAI


def build_model(provider: str, model_name: str):
    """Build a LangChain chat model for the given provider and model name.

    Returns the model wrapped with structured output for AgentOutput schema.
    Import AgentOutput inside to avoid circular imports.
    """
    from services.views import AgentOutput

    if provider == "anthropic":
        base = ChatAnthropicVertex(
            model_name=model_name,
            project=os.getenv("ANTHROPIC_PROJECT_ID", ""),
            location=os.getenv("ANTHROPIC_LOCATION", "us-east5"),
            max_tokens=4096,
        )
    elif provider == "azure":
        base = AzureChatOpenAI(
            temperature=0.0,
            azure_deployment=model_name,
            azure_endpoint=f"https://{os.getenv('AZURE_OPENAI_API_INSTANCE_NAME', '')}.openai.azure.com",
            api_key=os.getenv("AZURE_OPENAI_API_KEY"),
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview"),
        )
    else:  # google (default)
        base = ChatGoogleGenerativeAI(
            model=model_name,
            temperature=1.0,
            api_key=os.getenv("GOOGLE_API_KEY"),
        )

    return base.with_structured_output(
        schema=AgentOutput.model_json_schema(),
        method="json_schema",
        include_raw=True,
    )
