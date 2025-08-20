"""
Job Application Automator

Automated job application form extraction and filling with Claude Desktop integration
via Model Context Protocol (MCP).

Features:
- Form extraction from job posting URLs
- Intelligent form filling with user data
- Cover letter generation
- Applied jobs tracking
- Claude Desktop MCP integration

Usage:
    pip install job-application-automator
    job-automator-setup
    
Then use with Claude Desktop by asking:
    "Extract form fields from https://company.com/careers/job-123"
    "Fill the form with my information..."
"""

__version__ = "1.0.2"
__author__ = "Job Automator Team"
__email__ = "contact@jobautomator.dev"

# Import main modules for convenience
from .form_extractor import SimpleFormExtractor
from .form_filler import SimpleFormFiller

__all__ = [
    "SimpleFormExtractor",
    "SimpleFormFiller",
]
