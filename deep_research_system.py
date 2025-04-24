import streamlit as st
from langchain_community.tools.tavily_search import TavilySearchResults
from langchain_core.prompts import ChatPromptTemplate
from langchain_groq import ChatGroq
from langgraph.graph import StateGraph, END
from typing import TypedDict, List, Dict, Any
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

# Initialize Groq and Tavily
llm = ChatGroq(model="gemma2-9b-it", temperature=0)
tavily_tool = TavilySearchResults(max_results=5)

# Define state structure
class ResearchState(TypedDict):
    query: str
    analyzed_query: Dict[str, Any]
    search_results: List[Dict[str, Any]]
    extracted_content: List[str]
    draft_answer: str
    final_answer: str
    followup_questions: str

# Step 1: Query Analyzer
def query_analyzer(state: ResearchState) -> ResearchState:
    prompt = ChatPromptTemplate.from_template(
        """Analyze this user query and extract key components.
Return a JSON like this:
{{"main_topic": "...", "subtopics": [...], "search_terms": [...]}}.
Query: {query}"""
    )
    chain = prompt | llm
    raw_output = chain.invoke({"query": state["query"]}).content
    try:
        state["analyzed_query"] = eval(raw_output.strip())
    except Exception as e:
        state["analyzed_query"] = {"main_topic": state["query"], "subtopics": [], "search_terms": [state["query"]]}
    return state

# Step 2: Research Agent (Tavily search)
def research_agent(state: ResearchState) -> ResearchState:
    search_terms = state["analyzed_query"].get("search_terms", [state["query"]])
    search_query = " ".join(search_terms)
    state["search_results"] = tavily_tool.invoke(search_query)
    return state

# Step 3: Content Extractor
def content_extractor(state: ResearchState) -> ResearchState:
    state["extracted_content"] = [r.get("content", "")[:1000] for r in state["search_results"]]
    return state

# Step 4: Draft Answer
def answer_drafter(state: ResearchState) -> ResearchState:
    prompt = ChatPromptTemplate.from_template(
        """Use the info below to answer the query concisely.
Query: {query}
Info: {content}
Answer:"""
    )
    chain = prompt | llm
    content = "\n".join(state["extracted_content"])
    state["draft_answer"] = chain.invoke({"query": state["query"], "content": content}).content
    return state

# Step 5: Refine Answer
def answer_refiner(state: ResearchState) -> ResearchState:
    prompt = ChatPromptTemplate.from_template(
        """Polish the following draft to make it more clear and structured.
Draft: {draft}
Final Answer:"""
    )
    chain = prompt | llm
    state["final_answer"] = chain.invoke({"draft": state["draft_answer"]}).content
    return state

# Step 6: Generate Follow-Up Questions
def generate_followups(state: ResearchState) -> ResearchState:
    prompt = ChatPromptTemplate.from_template(
        """Based on the final answer, suggest 3 thoughtful follow-up questions the user might ask.
Answer: {answer}
Questions:"""
    )
    chain = prompt | llm
    state["followup_questions"] = chain.invoke({"answer": state["final_answer"]}).content
    return state

# Create LangGraph Workflow
workflow = StateGraph(ResearchState)
workflow.add_node("query_analyzer", query_analyzer)
workflow.add_node("research_agent", research_agent)
workflow.add_node("content_extractor", content_extractor)
workflow.add_node("answer_drafter", answer_drafter)
workflow.add_node("answer_refiner", answer_refiner)
workflow.add_node("generate_followups", generate_followups)

# Define graph edges
workflow.set_entry_point("query_analyzer")
workflow.add_edge("query_analyzer", "research_agent")
workflow.add_edge("research_agent", "content_extractor")
workflow.add_edge("content_extractor", "answer_drafter")
workflow.add_edge("answer_drafter", "answer_refiner")
workflow.add_edge("answer_refiner", "generate_followups")
workflow.add_edge("generate_followups", END)

graph = workflow.compile()

# Runner function
def run_research_system(query: str) -> ResearchState:
    initial_state = ResearchState(
        query=query,
        analyzed_query={},
        search_results=[],
        extracted_content=[],
        draft_answer="",
        final_answer="",
        followup_questions=""
    )
    return graph.invoke(initial_state)

# Streamlit UI
# Streamlit UI - Chatbot Style
st.set_page_config(page_title="AI Research Chatbot", layout="wide")
st.title("🤖 Research Chatbot")

# Initialize chat history
if "messages" not in st.session_state:
    st.session_state.messages = []

# Display chat messages
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# User input
user_input = st.chat_input("Ask me anything...")
if user_input:
    # Add user message to chat history
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    # Call the research agent pipeline
    with st.spinner("Thinking..."):
        result = run_research_system(user_input)
        answer = result["final_answer"]

        # Construct a response with sources and follow-ups
        response = answer
        if result["search_results"]:
            response += "\n\n**Sources:**\n"
            for r in result["search_results"]:
                title = r.get("title", "Untitled")
                url = r.get("url", "#")
                response += f"- [{title}]({url})\n"

        if result["followup_questions"]:
            response += "\n**Follow-up questions:**\n" + result["followup_questions"]

    # Add bot message to chat history
    st.session_state.messages.append({"role": "assistant", "content": response})

    with st.chat_message("assistant"):
        st.markdown(response)
