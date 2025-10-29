import streamlit as st
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.embeddings import SentenceTransformerEmbeddings
from langchain.vectorstores import Chroma
from langchain.chains import ConversationalRetrievalChain
from langchain.chat_models import ChatOpenAI
from langchain import HuggingFacePipeline
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM, pipeline
import os
from pypdf import PdfReader
from io import BytesIO

# -------------------- SETUP --------------------

st.title("💬 Chat with Your Documents")

# Create file uploader (for .txt and .pdf)
uploaded_files = st.file_uploader(
    "Upload .txt or .pdf files",
    type=["txt", "pdf"],
    accept_multiple_files=True
)

# Sidebar controls
st.sidebar.header("Settings")
chunk_size = st.sidebar.number_input("Chunk size (characters)", 500, 4000, 1000)
chunk_overlap = st.sidebar.number_input("Chunk overlap", 0, 500, 200)
top_k = st.sidebar.slider("Number of chunks to retrieve", 1, 10, 4)
use_openai = st.sidebar.checkbox("Use OpenAI (needs OPENAI_API_KEY)", value=False)

# -------------------- STEP 1: READ FILES --------------------

def read_pdf(file_bytes):
    reader = PdfReader(BytesIO(file_bytes))
    text = ""
    for page in reader.pages:
        text += page.extract_text() or ""
    return text

def read_txt(file_bytes):
    return file_bytes.decode("utf-8")

docs = []
if uploaded_files:
    st.info("Processing uploaded files...")
    for file in uploaded_files:
        if file.name.lower().endswith(".pdf"):
            text = read_pdf(file.read())
        else:
            text = read_txt(file.read())
        docs.append({"name": file.name, "text": text})
    st.success(f"✅ {len(docs)} document(s) loaded!")

# -------------------- STEP 2: CHUNKING --------------------

if docs:
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap
    )
    all_chunks = []
    for doc in docs:
        chunks = text_splitter.split_text(doc["text"])
        all_chunks.extend([{"text": chunk, "source": doc["name"]} for chunk in chunks])
    st.write(f"🔹 Created {len(all_chunks)} text chunks total.")

# -------------------- STEP 3: BUILD VECTOR DATABASE --------------------

    st.info("Creating embeddings and storing them in Chroma...")
    embeddings = SentenceTransformerEmbeddings(model_name="all-MiniLM-L6-v2")
    vectorstore = Chroma.from_texts(
        texts=[chunk["text"] for chunk in all_chunks],
        embedding=embeddings,
        metadatas=[{"source": chunk["source"]} for chunk in all_chunks]
    )
    st.success("✅ Vector database ready!")

# -------------------- STEP 4: CHOOSE LANGUAGE MODEL --------------------

    if use_openai and os.getenv("OPENAI_API_KEY"):
        llm = ChatOpenAI(temperature=0)
    else:
        model_name = "google/flan-t5-small"
        tokenizer = AutoTokenizer.from_pretrained(model_name)
        model = AutoModelForSeq2SeqLM.from_pretrained(model_name)
        hf_pipeline = pipeline("text2text-generation", model=model, tokenizer=tokenizer)
        llm = HuggingFacePipeline(pipeline=hf_pipeline)

# -------------------- STEP 5: CREATE RAG CHAIN --------------------

    retriever = vectorstore.as_retriever(search_kwargs={"k": top_k})
    qa_chain = ConversationalRetrievalChain.from_llm(llm=llm, retriever=retriever)

    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []

    st.subheader("Ask Questions about Your Documents")
    user_question = st.text_input("Enter your question:")

    if st.button("Ask"):
        if not user_question:
            st.warning("Please type a question.")
        else:
            with st.spinner("Thinking..."):
                result = qa_chain({"question": user_question, "chat_history": st.session_state.chat_history})
                answer = result["answer"]
                st.session_state.chat_history.append((user_question, answer))

                st.markdown(f"**Answer:** {answer}")

                # Show top sources
                st.markdown("**Sources:**")
                for doc in result.get("source_documents", []):
                    st.write(f"- {doc.metadata.get('source', 'Unknown file')}")

    if st.session_state.chat_history:
        st.markdown("---")
        st.markdown("### Conversation History")
        for q, a in reversed(st.session_state.chat_history):
            st.markdown(f"**Q:** {q}")
            st.markdown(f"**A:** {a}")
else:
    st.info("👆 Upload some files above to get started.")

