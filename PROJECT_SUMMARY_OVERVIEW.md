# Project Overview

## What the project is

This repository started from an AI agent template. The intended system combines a web API, an AI assistant, optional search/tools, video analysis, testing, Docker, and activity logging.

The current repository contains two related but separate pieces:

- A video privacy pipeline that looks for license plates and faces and applies blur to them. It runs from the command line and can process a video or webcam input.
- A small web backend with a chat endpoint and a readiness/status endpoint. The chat currently passes the user’s message through a basic example workflow; it is not yet the intended incident-analysis assistant.

## What is currently in place

The backend can start, expose a health check, restrict protected endpoints with an API key, validate chat messages, and run its basic workflow. Automated tests cover these areas and several video-processing helpers.

The project also includes Docker setup, continuous integration for linting and tests, sample incident datasets, video-analysis evaluation files, and scripts for setup and AI-usage logging. The video tool can use a graphics card when available and otherwise falls back to the computer’s processor.

## Current status and evidence

The backend should be understood as a working template or early example, not a completed domain product. Its analysis and response steps are placeholders, and the planned language model, search, database, and document-retrieval features are not active. No user-facing web frontend is present, and the video tool is not connected to the backend: there is no upload, processing-job, result, or download workflow through the API.

Video privacy performance is not yet production-ready. The checked-in validation report found 0 of 12 benchmark license-plate boxes matched by the final configuration. Face recall could not be measured because the benchmark contained no usable face boxes. The report recommends collecting and labeling at least 100–200 project-specific frames, then fine-tuning or replacing the models and repeating the evaluation.

Other documentation still needs alignment with the implementation. In particular, the video guide describes an older file location and output location, while the current tool uses a different source location and a machine-specific output folder. General evaluation, journal, and worklog documents are also still largely templates. The project has some broad dependency versions, and continuous integration does not currently build Docker images, run the video benchmark, perform secret scanning, or deploy the system.

## Main priorities

1. Validate and improve video privacy detection on project-specific footage before making production or privacy-completeness claims.
2. Correct the video instructions and make output locations reproducible across machines.
3. Replace the example AI workflow with the intended incident-analysis process, including the real model, tools, and search/retrieval features.
4. Add the missing frontend and complete the backend-to-video workflow if they are required for the final product.
5. Complete evaluation, project records, presentation, and delivery materials.
6. Align setup, security configuration, testing, Docker, and deployment expectations before handoff.

Overall, the repository demonstrates a protected API skeleton and an independently runnable video-blurring experiment, with tests and supporting project materials. It does not yet demonstrate a complete, validated incident-analysis product.
