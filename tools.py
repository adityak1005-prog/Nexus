"""
tools.py — LangChain tools available to the agent
Currently: Google Docs export
Auth: OAuth via credentials.json / token.json (same pattern as your test)
"""

import os
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from langchain_core.tools import tool
import streamlit as st

SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive"
]

def get_google_credentials():
    """Cloud-ready OAuth flow using Streamlit Secrets."""
    creds = None
    
    # 1. Check if we are running in the cloud and have secrets
    if "google_token" in st.secrets:
        token_info = dict(st.secrets["google_token"])
        creds = Credentials.from_authorized_user_info(token_info, SCOPES)
    
    # 2. Fallback for local testing if token.json exists on your laptop
    elif os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    
    # 3. Refresh the token if it has expired
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        
    return creds


@tool
def export_summary_to_google_doc(title: str, summary_text: str) -> str:
    """
    Creates a new Google Doc with the given title and inserts the summary text.
    Use this whenever the user wants to save or export a summary to Google Drive.
    Returns the clickable document URL.
    """
    creds = get_google_credentials()
    try:
        docs_service = build("docs", "v1", credentials=creds)
        doc          = docs_service.documents().create(body={"title": title}).execute()
        document_id  = doc.get("documentId")

        docs_service.documents().batchUpdate(
            documentId=document_id,
            body={"requests": [{"insertText": {"location": {"index": 1}, "text": summary_text}}]}
        ).execute()

        doc_url = f"https://docs.google.com/document/d/{document_id}/edit"
        return f"Successfully created document! Link: {doc_url}"
    except Exception as e:
        return f"Error creating document: {str(e)}"


if __name__ == "__main__":
    print("Testing Google Auth...")
    get_google_credentials()
    print("Done — token.json created.")
