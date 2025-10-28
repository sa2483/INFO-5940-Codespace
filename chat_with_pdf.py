import streamlit as st

st.title("📄 Upload and Preview Text Files")

# Let users choose one or more text files
uploaded_files = st.file_uploader(
    "Upload your .txt files to begin",
    type=["txt"],
    accept_multiple_files=True
)

# When files are uploaded
if uploaded_files:
    st.success(f"✅ {len(uploaded_files)} file(s) uploaded successfully!")

    # Go through each uploaded file
    for file in uploaded_files:
        # Read the text inside
        text = file.read().decode("utf-8")
        st.write(f"**File name:** {file.name}")
        st.text_area("File preview:", text[:500], height=200)
else:
    st.info("Please upload at least one .txt file to continue.")
