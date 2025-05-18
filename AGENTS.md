# Contributor Guide

## Dev Environment Tips

This system will consist of multiple specialized agents working collaboratively:
- FetcherAgent: Retrieves new research papers from sources like ArXiv or Semantic Scholar.
- SummarizerAgent: Generates concise summaries of fetched papers.
- CriticAgent: Evaluates the quality and relevance of the summaries.
- TrendAnalyzerAgent: Identifies emerging trends across multiple papers.
- PlannerAgent: Recommends next steps or further readings based on insights.
These agents will communicate via the A2A protocol, enabling dynamic task delegation and shared context.
We can create a .env file to store the API keys. This should be added to gitignore

*Recommended Tech Stack*
1. Programming Language - Python: Preferred for its rich ecosystem and extensive support for AI and machine learning libraries.
2. Agent Orchestration
    - LangGraph: Facilitates the creation of multi-agent workflows with stateful interactions.
    - CrewAI: Offers a framework for defining agent roles and managing their interactions.
3. Language Models
    - OpenAI GPT-4: For natural language understanding and generation tasks.
4. Data Retrieval and Processing
    - ArXiv API / Semantic Scholar API: For fetching research papers.
    - BeautifulSoup / Scrapy: For web scraping tasks.
    - PyPDF2 / pdfminer.six: For extracting text from PDF documents.
5. Data Storage
    - sqllite: Lightweight database for storing metadata and summaries.
    - Pinecone / FAISS: For vector-based similarity search and trend analysis.
6. User Interface
    - Streamlit: Rapid development of interactive web applications.
    - Flask / FastAPI: For building RESTful APIs if needed.
7. Deployment
    - Docker: Containerization for consistent deployment across environments.
    - AWS: Cloud platforms for hosting the application.

*Integration Strategy*
- Agent Communication: Utilize LangGraph to define the workflow and communication between agents, ensuring each agent can pass tasks and data to others seamlessly.
- Task Delegation: Implement CrewAI to assign specific roles and responsibilities to each agent, allowing for dynamic task allocation based on the current context.
- Data Flow:
    - FetcherAgent retrieves new papers and passes them to SummarizerAgent.
    - SummarizerAgent generates summaries and sends them to CriticAgent.
    - CriticAgent evaluates and provides feedback, which is stored in the database.
    - TrendAnalyzerAgent analyzes stored data to identify trends.
    - PlannerAgent uses insights to recommend further readings or actions.
    - User Interaction: Develop a Streamlit app to allow users to input queries, view summaries, critiques, and trend analyses.

## Testing Instructions
- Add or update tests for the code you change, even if nobody asked.
- After moving files or changing imports, run pnpm lint --filter <project_name> to be sure ESLint and TypeScript rules still pass.
- Fix any test or type errors until the whole suite is green.

## PR instructions
Title format: [<project_name>] <Title>