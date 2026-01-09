from agent_framework.devui import serve
import os

from .stock import build_workflow as stock_workflow
from .supplier_review import build_workflow as supplier_review_workflow
from .insights import get_workflow as get_insights_workflow

def main():
    port = os.environ.get("PORT", 8090)

    # Launch server with the workflow
    serve(entities=[stock_workflow(), supplier_review_workflow(), get_insights_workflow()], port=int(port), auto_open=False, tracing_enabled=False)


if __name__ == "__main__":
    main()
