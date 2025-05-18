Research Assistant Agent


                ┌───────────────┐
   text_input → │  Streamlit UI │─┐
                └───────────────┘ │  starts worker-thread
                                   ▼
                           ┌────────────────┐
                           │ run_pipeline() │──> LangGraph (all agents)
                           └────────────────┘
                                     │ puts log lines
                                     ▼
                          ┌───────────────────┐
                          │   log_queue       │
                          └───────────────────┘
                                     │
                    UI polls ⇒   live INFO log stream
