#!/usr/bin/env python3
"""
MCP Server for Form Automation
Provides two tools:
1. simple_form_extraction - Extract form data from a URL
2. simple_form_filling - Fill form with provided data

This server implements the Model Context Protocol (MCP) specification
for seamless integration with Claude Desktop and other MCP clients.
"""

import asyncio
import json
import logging
import sys
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from datetime import datetime, timedelta

from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent

# Handle imports for both module and script execution
try:
    from .form_extractor import SimpleFormExtractor
    from .form_filler import SimpleFormFiller
except ImportError:
    # Fallback for direct script execution
    from form_extractor import SimpleFormExtractor
    from form_filler import SimpleFormFiller

# Configure logging
import tempfile
import os
from pathlib import Path

# Create a proper log directory
try:
    # Try to use user's home directory first
    log_dir = Path.home() / '.job-automator'
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / 'mcp_server.log'
except (PermissionError, OSError):
    # Fallback to temporary directory
    log_file = Path(tempfile.gettempdir()) / 'job_automator_mcp_server.log'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Initialize FastMCP server
mcp = FastMCP("form-automation-server")

# Global state to maintain form filling process
form_filling_state = {
    "browser_active": False,
    "current_session": None,
    "form_data": None
}

@mcp.tool()
async def simple_form_extraction(url: Optional[str] = None, urls: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Extract form structure and fields from one or more web page URLs.
    
    Args:
        url: A single URL starting with http:// or https://
        urls: A list of URLs (max 5) to extract in parallel
        
    Returns:
        A dictionary containing a summary and an array of per-URL extraction results.
        Each result mirrors the previous single-URL response fields.
    
    Examples:
        Single URL call:
          Input parameters:
            { "url": "https://example.com/jobs/123" }
          Response shape:
            {
              "status": "success",
              "total_urls": 1,
              "succeeded": 1,
              "failed": 0,
              "results": [ { per-url result object } ]
            }
        
        Multiple URLs (max 5):
          Input parameters:
            { "urls": [
                "https://example.com/jobs/123",
                "https://careers.example.org/apply/456"
            ] }
          Response shape:
            {
              "status": "success|partial|error",
              "total_urls": 2,
              "succeeded": 2,
              "failed": 0,
              "results": [ { per-url }, { per-url } ]
            }
        
        Per-URL result object:
            {
              "status": "success",
              "message": "Successfully extracted 12 form fields",
              "url": "https://...",
              "job_title": "Software Engineer",
              "company": "Acme Corp",
              "total_fields": 12,
              "required_fields": 6,
              "form_context": { ... },
              "user_input_template": [ ... ],
              "extracted_data_file": "extracted_form_data_20250813_101530_123456.json",
              "extracted_data_path": "D:/.../extracted_form_data/extracted_form_data_...json",
              "timestamp": "2025-08-13T10:15:30.123456"
            }
    """
    try:
        # Normalize inputs to a list while maintaining backward compatibility
        url_list: List[str] = []
        if urls and isinstance(urls, list):
            url_list = urls
        elif url and isinstance(url, str):
            url_list = [url]
        else:
            raise ValueError("Provide 'url' (string) or 'urls' (list of up to 5 URLs)")

        # Enforce max of 5 URLs per call
        if len(url_list) > 5:
            raise ValueError("Maximum of 5 URLs allowed per call")

        # Basic validation
        for u in url_list:
            if not u or not isinstance(u, str) or not u.startswith(('http://', 'https://')):
                raise ValueError(f"Invalid URL provided: {u}. URL must start with http:// or https://")

        logger.info(f"Starting form extraction for {len(url_list)} URL(s)")

        # Ensure output directory exists
        extracted_data_dir = Path(__file__).parent.parent / "extracted_form_data"
        extracted_data_dir.mkdir(exist_ok=True)

        # Concurrency limit (parallel but bounded)
        concurrency = min(5, len(url_list))
        sem = asyncio.Semaphore(concurrency)

        async def extract_one(target_url: str) -> Dict[str, Any]:
            async with sem:
                try:
                    logger.info(f"Extracting form for URL: {target_url}")
                    extractor = SimpleFormExtractor()
                    form_data = await extractor.extract_form_data(target_url)

                    # Unique filename with microseconds to avoid collisions in parallel writes
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                    output_file = f"extracted_form_data_{timestamp}.json"
                    output_path = extracted_data_dir / output_file

                    with open(output_path, 'w', encoding='utf-8') as f:
                        json.dump(form_data, f, indent=2, ensure_ascii=False)

                    logger.info(f"Form extraction complete for {target_url}. Fields: {form_data.get('total_fields', 0)}")

                    return {
                        "status": "success",
                        "message": f"Successfully extracted {form_data.get('total_fields', 0)} form fields",
                        "url": target_url,
                        "job_title": form_data.get('job_title'),
                        "company": form_data.get('company'),
                        "total_fields": form_data.get('total_fields', 0),
                        "required_fields": form_data.get('required_fields', 0),
                        "form_context": form_data.get('form_context', {}),
                        "user_input_template": form_data.get('user_input_template', {}),
                        "extracted_data_file": output_file,
                        "extracted_data_path": str(output_path),
                        "timestamp": form_data.get('timestamp')
                    }
                except Exception as e:
                    error_msg = f"Form extraction failed for {target_url}: {str(e)}"
                    logger.error(error_msg)
                    return {
                        "status": "error",
                        "message": error_msg,
                        "url": target_url,
                        "error_details": str(e)
                    }

        # Run extractions in parallel
        tasks = [asyncio.create_task(extract_one(u)) for u in url_list]
        results = await asyncio.gather(*tasks)

        success_count = sum(1 for r in results if r.get("status") == "success")
        error_count = len(results) - success_count

        overall_status = "success" if success_count > 0 and error_count == 0 else ("partial" if success_count > 0 else "error")

        return {
            "status": overall_status,
            "total_urls": len(url_list),
            "succeeded": success_count,
            "failed": error_count,
            "results": results
        }

    except Exception as e:
        error_msg = f"Form extraction failed: {str(e)}"
        logger.error(error_msg)
        return {
            "status": "error",
            "message": error_msg,
            "error_details": str(e),
            "results": []
        }

def _log_job_application(url: str, job_title: str, company: str) -> None:
    """Log job application details to applied_jobs.txt file."""
    try:
        # Create applied_jobs.txt file path
        applied_jobs_file = Path(__file__).parent.parent / "applied_jobs.txt"
        
        # Get current timestamp
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Format log entry - only timestamp and URL
        log_entry = f"{timestamp} | {url}\n"
        
        # Append to file (create if doesn't exist)
        with open(applied_jobs_file, 'a', encoding='utf-8') as f:
            f.write(log_entry)
        
        logger.info(f"Logged job application: {url}")
        
    except Exception as e:
        logger.error(f"Failed to log job application: {e}")

@mcp.tool()
async def simple_form_filling(form_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Fill a form with the provided data. The form filler will navigate to the URL,
    fill all the fields, and keep the browser open for user review and submission.
    
    COMPREHENSIVE FIELD FILLING STRATEGY: This tool is designed to fill ALMOST ALL fields 
    in the form with meaningful values. You should strive to provide values for every field 
    possible, using inference, context clues, and reasonable assumptions. Only leave fields 
    unfilled if they are absolutely impossible to infer or would make no logical sense to fill.
    
    FIELD FILLING GUIDELINES:
    - Personal Info: Always fill name, email, phone, address fields
    - Experience: Infer years of experience from resume/background context
    - Skills: Extract and match relevant skills from user's background
    - Education: Fill graduation years, degrees, institutions if mentioned
    - Demographics: Infer demographic information answers from resume content, education, 
      work history, and name patterns. Select the most aligning demographic options from 
      dropdown choices when available (ethnicity, veteran status, disability status, etc.)
    - Preferences: Make reasonable assumptions for salary, location, start date
    - Optional Fields: Fill them anyway if you can reasonably infer the information
    - Dropdown Selections: Choose the most appropriate option based on context
    - Yes/No Questions: Make logical decisions based on typical job seeker preferences
    - Text Areas: Provide concise but relevant responses for "why interested", etc.
    
    CRITICAL FILE REQUIREMENTS: Before calling this tool, ALWAYS check if the user has provided 
    a resume/CV file path in the conversation. If any file field (especially resume/CV) 
    has an empty value or if the user hasn't mentioned their resume location in the chat, 
    you MUST ask the user to provide the resume file path before proceeding. Resume fields 
    typically have IDs like 'resume_cv', 'resume', 'cv', or questions containing 'Resume', 
    'CV', or 'Upload'. CRITICAL: Resume/CV fields should NEVER be left empty, even if 
    marked as optional or not required - always ensure a resume path is provided.
    
    COVER LETTER REQUIREMENT: If any cover letter field exists (IDs like 'cover_letter', 
    'cover', 'letter', or questions containing 'Cover Letter', 'Cover', 'Letter'), you MUST 
    use the 'create_cover_letter' tool to generate a personalized, enthusiastic but professional 
    cover letter specifically tailored to the company and position. This tool will create the 
    cover letter file(if you give the content) and return the file path which should be used as the value for the cover 
    letter field. Cover letter fields should NEVER be left empty if they exist, regardless of 
    whether they are required or optional - always generate and provide a real cover letter 
    file path using the create_cover_letter tool.
    
    MAXIMIZE COMPLETION RATE: The goal is to achieve near 100% form completion. Think creatively 
    about how to fill fields based on context, make educated guesses where appropriate if options available for the field only select value from those options if sample options then insert value that fits best for the question. This maximizes 
    the chance of successful form submission and reduces manual work for the user.
    
    Do not attempt form filling without the user explicitly providing their resume path in 
    the conversation and without generating cover letters for any cover letter fields that exist.
    
    Args:
        form_data: Form data structure with filled values. Only requires 3 core fields:
                  'url', 'form_context', and 'user_input_template' with filled values.
                  Additional fields from extraction output are optional and ignored.
                  
    Required structure (core fields only):
    {
        "url": "https://example.com/job-application",
        "form_context": {
            "is_iframe": false,
            "iframe_src": null,
            "iframe_selector": null,
            "iframe_index": 0,
            "wait_strategy": "networkidle",
            "load_timeout": 15000
        },
        "user_input_template": [   // This array should be filled with values
            {
                "id": "first_name",
                "question": "First Name", 
                "value": "John",           // <- Fill this
                "required": true,
                "type": "text"
            },
            {
                "id": "email",
                "question": "Email",
                "value": "john@example.com",  // <- Fill this
                "required": true,
                "type": "email"
            }
            // ... more fields with filled values
        ]
    }
    
    Optional fields (from extraction output - can be included but will be ignored):
    {
        "timestamp": "2025-07-14T16:20:01.030834", 
        "job_title": "Software Engineer",
        "company": "Example Company",
        "total_fields": 15,
        "required_fields": 8,
        "fields": [...]  // Original field definitions - NOT REQUIRED, ignored by filler
    }
                  
    Returns:
        A dictionary indicating the success/failure of the form filling operation
    """
    global form_filling_state
    
    try:
        logger.info("Starting form filling process")
        
        # Validate form data structure - only 3 core fields required
        required_keys = ['url', 'form_context', 'user_input_template']
        missing_keys = [key for key in required_keys if key not in form_data]
        
        if missing_keys:
            raise ValueError(f"Missing required keys in form_data: {missing_keys}")
        
        # Validate that user_input_template is a list (array) as expected
        if not isinstance(form_data.get('user_input_template'), list):
            raise ValueError("user_input_template must be an array/list of field objects, not a dictionary")
        
        # Extract key information
        url = form_data.get('url')
        user_input_template = form_data.get('user_input_template', [])
        job_title = form_data.get('job_title', 'N/A')
        company = form_data.get('company', 'N/A')
        total_fields = form_data.get('total_fields', 0)
        
        # Validate required data
        if not url:
            raise ValueError("URL is required")
        if not user_input_template:
            raise ValueError("user_input_template is required")
        
        logger.info(f"Processing form data for: {job_title} at {company}")
        logger.info(f"Form URL: {url}")
        logger.info(f"Total fields to fill: {len(user_input_template)}")
        
        # Save form data to a temporary JSON file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        temp_file = f"temp_form_data_{timestamp}.json"
        temp_path = Path(__file__).parent.parent / temp_file
        
        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump(form_data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Form data saved to temporary file: {temp_file}")
        
        # Initialize form filler
        filler = SimpleFormFiller()
        
        # Log the job application
        _log_job_application(url, job_title, company)
        
        # Store state for potential cleanup
        form_filling_state["form_data"] = form_data
        form_filling_state["temp_file"] = temp_path
        
        # Start form filling in background (non-blocking)
        # This allows the MCP tool to return success while the browser continues running
        async def fill_form_background():
            try:
                form_filling_state["browser_active"] = True
                success = await filler.fill_form(str(temp_path))
                
                if success:
                    logger.info("Form filling completed successfully - browser remains open for user review")
                else:
                    logger.error("Form filling failed")
                    
            except Exception as e:
                logger.error(f"Background form filling error: {e}")
            finally:
                form_filling_state["browser_active"] = False
                # Clean up temp file
                try:
                    if temp_path.exists():
                        temp_path.unlink()
                        logger.info(f"Cleaned up temporary file: {temp_file}")
                except Exception as cleanup_error:
                    logger.warning(f"Could not clean up temp file: {cleanup_error}")
        
        # Start the background task
        asyncio.create_task(fill_form_background())
        
        # Return success immediately while form filling continues in background
        filled_fields_count = len([field for field in user_input_template 
                                 if field.get('value') and str(field.get('value', '')).strip()])
        
        return {
            "status": "success",
            "message": "Form filling process started successfully",
            "url": url,
            "job_title": job_title,
            "company": company,
            "fields_to_fill": filled_fields_count,
            "total_fields": total_fields,
            "browser_status": "opening",
            "note": "The browser will open and fill the form. It will remain open for you to review and submit manually.",
            "temp_data_file": temp_file,
            "form_structure": "Using core fields: url, form_context, user_input_template (additional fields ignored)"
        }
        
    except Exception as e:
        error_msg = f"Form filling failed: {str(e)}"
        logger.error(error_msg)
        
        # Clean up temp file if it was created
        if 'temp_path' in locals() and temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass
        
        return {
            "status": "error",
            "message": error_msg,
            "error_details": str(e),
            "url": form_data.get('url', 'unknown')
        }

@mcp.tool()
async def create_cover_letter(
    company_name: str,
    job_title: str,
    cover_letter_content: str,
    applicant_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create a personalized cover letter file and return the file path.
    
    This tool creates a professionally formatted cover letter as a text file that can be 
    used for job application form uploads. The cover letter should be tailored to the 
    specific company and position.
    
    Args:
        company_name: Name of the company/organization
        job_title: Title of the position being applied for
        cover_letter_content: The main content/body of the cover letter
        applicant_name: Name of the applicant (optional, will be added if provided)
        
    Returns:
        A dictionary containing the file path and creation status
    """
    try:
        logger.info(f"Creating cover letter for {job_title} at {company_name}")
        
        # Validate inputs
        if not company_name or not job_title or not cover_letter_content:
            raise ValueError("Company name, job title, and cover letter content are required")
        
        # Create timestamp for unique filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Clean company and job title for filename (remove special characters)
        safe_company = "".join(c for c in company_name if c.isalnum() or c in (' ', '-', '_')).strip()
        safe_job = "".join(c for c in job_title if c.isalnum() or c in (' ', '-', '_')).strip()
        safe_company = safe_company.replace(' ', '_')
        safe_job = safe_job.replace(' ', '_')
        
        # Create filename
        filename = f"cover_letter_{safe_company}_{safe_job}_{timestamp}.txt"
        # Save to cover_letters directory
        cover_letters_dir = Path(__file__).parent.parent / "cover_letters"
        cover_letters_dir.mkdir(exist_ok=True)  # Ensure directory exists
        file_path = cover_letters_dir / filename
        
        # Format the cover letter content
        formatted_content = f"""Dear Hiring Manager,

{cover_letter_content.strip()}

Sincerely,
{applicant_name if applicant_name else "[Your Name]"}

---
Cover Letter for: {job_title}
Company: {company_name}
Created: {datetime.now().strftime("%B %d, %Y")}
"""
        
        # Write the cover letter to file
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(formatted_content)
        
        logger.info(f"Cover letter created successfully: {filename}")
        
        return {
            "status": "success",
            "message": f"Cover letter created successfully for {job_title} at {company_name}",
            "file_path": str(file_path),
            "filename": filename,
            "company_name": company_name,
            "job_title": job_title,
            "file_size_bytes": file_path.stat().st_size,
            "created_timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        error_msg = f"Cover letter creation failed: {str(e)}"
        logger.error(error_msg)
        return {
            "status": "error",
            "message": error_msg,
            "error_details": str(e),
            "company_name": company_name,
            "job_title": job_title
        }

@mcp.tool()
async def get_applied_jobs() -> str:
    """
    ARTIFACT-ONLY TOOL: Retrieve all applied job applications and display them in a beautiful markdown format.
    
    CRITICAL: This tool ALWAYS returns the complete content as Markdown text that MUST be rendered 
    as an artifact immediately without any additional commentary or explanation. Claude MUST create 
    a Markdown artifact directly using the returned content and suppress all text responses.
    
    FORMATTING REQUIREMENT: The response is pre-formatted markdown content that should be rendered 
    as-is in an artifact. Do not add any additional text, explanations, or summaries - just create 
    the artifact with the returned markdown content.
    
    Returns:
        A beautifully formatted markdown string showing all applied jobs, most recent first
    """
    try:
        # Path to applied jobs log file
        applied_jobs_file = Path(__file__).parent.parent / "applied_jobs.txt"
        
        # Check if file exists
        if not applied_jobs_file.exists():
            return """# 📋 Applied Jobs Dashboard

## No Applications Yet

You haven't applied to any jobs yet. Start applying to see your application history here!

---
*This dashboard automatically tracks all job applications made through the form filler tool.*
"""
        
        # Read and parse the log file
        applications = []
        with open(applied_jobs_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # Parse each line (supports both formats: timestamp|url AND timestamp|company|job_title|url)
        for line in lines:
            line = line.strip()
            if line and '|' in line:
                try:
                    parts = [part.strip() for part in line.split('|')]
                    
                    if len(parts) == 2:
                        # New format: timestamp | url
                        timestamp, url = parts[0], parts[1]
                        company = "Unknown Company"
                        job_title = "Job Application"
                        
                        # Try to extract company from common URL patterns
                        if 'careers.google.com' in url:
                            company = "Google"
                        elif 'careers.microsoft.com' in url:
                            company = "Microsoft"
                        elif 'jobs.apple.com' in url:
                            company = "Apple"
                        elif 'metacareers.com' in url:
                            company = "Meta"
                        elif 'amazon.jobs' in url:
                            company = "Amazon"
                        elif 'meraki.cisco.com' in url:
                            company = "Cisco"
                        elif 'greenhouse.io' in url:
                            # Extract company from greenhouse URLs
                            try:
                                company_part = url.split('greenhouse.io/')[1].split('/')[0]
                                company = company_part.title()
                            except:
                                company = "Company (via Greenhouse)"
                        elif 'workday.com' in url:
                            company = "Company (via Workday)"
                        elif 'lever.co' in url:
                            company = "Company (via Lever)"
                        else:
                            # Try to extract domain name as company
                            try:
                                from urllib.parse import urlparse
                                domain = urlparse(url).netloc
                                if domain:
                                    company = domain.replace('www.', '').replace('.com', '').replace('.org', '').replace('.net', '').title()
                            except:
                                pass
                        
                    elif len(parts) >= 4:
                        # Old format: timestamp | company | job_title | url
                        timestamp, company, job_title, url = parts[0], parts[1], parts[2], parts[3]
                        
                        # Handle N/A values from old format
                        if company == "N/A" or not company:
                            company = "Unknown Company"
                            # Try to detect from URL
                            if 'meraki.cisco.com' in url:
                                company = "Cisco"
                            elif 'clickhouse' in url.lower():
                                company = "ClickHouse"
                        
                        if job_title == "N/A" or not job_title:
                            job_title = "Job Application"
                    
                    else:
                        # Invalid format, skip
                        continue
                    
                    applications.append({
                        'timestamp': timestamp,
                        'company': company,
                        'job_title': job_title,
                        'url': url
                    })
                    
                except Exception as e:
                    logger.debug(f"Error parsing line: {line} - {e}")
                    continue
        
        # Sort by timestamp (most recent first)
        applications.sort(key=lambda x: x['timestamp'], reverse=True)
        
        # Generate beautiful markdown content
        if not applications:
            return """# 📋 Applied Jobs Dashboard

## No Valid Applications Found

The log file exists but contains no valid application entries.

---
*This dashboard automatically tracks all job applications made through the form filler tool.*
"""
        
        # Create markdown content
        markdown_content = f"""# 📋 Applied Jobs Dashboard

## 🎯 Application Summary
- **Total Applications:** {len(applications)}
- **Last Updated:** {datetime.now().strftime("%B %d, %Y at %I:%M %p")}

---

## 📈 Recent Applications

"""
        
        # Add each application
        for i, app in enumerate(applications, 1):
            # Format timestamp for better readability
            try:
                dt = datetime.strptime(app['timestamp'], "%Y-%m-%d %H:%M:%S")
                formatted_date = dt.strftime("%B %d, %Y")
                formatted_time = dt.strftime("%I:%M %p")
            except:
                formatted_date = app['timestamp']
                formatted_time = ""
            
            markdown_content += f"""### {i}. {app['job_title']}
**🏢 Company:** {app['company']}  
**📅 Applied:** {formatted_date} at {formatted_time}  
**🔗 Application URL:** {app['url']}

---

"""
        
        # Add footer
        markdown_content += f"""
## 📊 Statistics

| Metric | Value |
|--------|-------|
| Total Applications | {len(applications)} |
| Unique Companies | {len(set(app['company'] for app in applications))} |
| This Month | {len([app for app in applications if app['timestamp'].startswith(datetime.now().strftime('%Y-%m'))])} |
| This Week | {len([app for app in applications if datetime.now().date() - datetime.strptime(app['timestamp'], '%Y-%m-%d %H:%M:%S').date() <= timedelta(days=7)])} |

---

*🤖 Automated tracking via Form Automation MCP Server*  
*📝 Applications logged by timestamp and URL (company names auto-detected from URLs)*
"""
        
        return markdown_content
        
    except Exception as e:
        error_msg = f"Error retrieving applied jobs: {str(e)}"
        logger.error(error_msg)
        return f"""# 📋 Applied Jobs Dashboard

## ❌ Error Loading Applications

An error occurred while loading your job applications:

```
{error_msg}
```

Please check the log files and try again.

---
*This dashboard automatically tracks all job applications made through the form filler tool.*
"""

# Add a health check tool
@mcp.tool()
async def health_check() -> Dict[str, Any]:
    """
    Check the health status of the form automation server.
    
    Returns:
        A dictionary containing the server status and active processes
    """
    return {
        "status": "healthy",
        "server": "form-automation-server",
        "version": "1.0.0",
        "browser_active": form_filling_state.get("browser_active", False),
        "current_session": form_filling_state.get("current_session") is not None,
        "timestamp": datetime.now().isoformat(),
        "tools_available": [
            "simple_form_extraction",
            "simple_form_filling",
            "create_cover_letter",
            "get_applied_jobs",
            "health_check"
        ]
    }

# Add a resource for server information
@mcp.resource("server://info")
def get_server_info() -> str:
    """Get information about the form automation server."""
    return f"""# Form Automation Server

This MCP server provides form automation capabilities for job applications and other web forms.

## Available Tools:

### 1. simple_form_extraction
Extracts form structure and fields from one or more web page URLs.
- Input: `url` (single URL) or `urls` (list, up to 5). Extracted in parallel.
- Output: An array of results (one per URL) with fields, labels, types, and requirements

Examples:
- Single:
  Parameters: {{ "url": "https://example.com/jobs/123" }}
- Multiple (max 5):
  Parameters: {{ "urls": ["https://example.com/jobs/123", "https://careers.example.org/apply/456"] }}

### 2. simple_form_filling  
Fills a form with provided data and keeps browser open for review.
- Input: Form data with 3 required fields: url, form_context, user_input_template
- Output: Success/failure status and browser management info
- Note: Additional fields from extraction output are optional and ignored

### 3. create_cover_letter
Creates a personalized cover letter file for job applications.
- Input: Company name, job title, cover letter content, and optional applicant name
- Output: File path of the created cover letter text file

### 4. get_applied_jobs
ARTIFACT-ONLY TOOL: Displays all applied job applications in beautiful markdown format.
- Input: None
- Output: Pre-formatted markdown content that MUST be rendered as an artifact
- Note: Always displays most recent applications first, automatically tracks all form submissions

### 5. health_check
Checks the server health and active processes.
- Input: None
- Output: Server status and active session information

## Workflow:
1. Use `simple_form_extraction` with a URL or up to 5 URLs to get form structure
2. Fill in the values in the returned template(s)
3. If cover letter fields exist, use `create_cover_letter` to generate cover letter files
4. Use `simple_form_filling` with the completed data to fill the form
5. Review and submit the form manually in the browser

## Server Status:
- Version: 1.0.0
- Active: {form_filling_state.get('browser_active', False)}
- Timestamp: {datetime.now().isoformat()}
"""

def main():
    """Main entry point for the MCP server."""
    logger.info("Starting Form Automation MCP Server...")
    
    # Add server information
    logger.info("Form Automation Server v1.0.0")
    logger.info("Available tools: simple_form_extraction, simple_form_filling, create_cover_letter, get_applied_jobs, health_check")
    logger.info("Protocol: Model Context Protocol (MCP)")
    
    try:
        # Run the FastMCP server
        mcp.run()
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Server error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
