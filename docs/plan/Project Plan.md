# Project Plan

> Historical planning document. Student identification numbers have been omitted.
> Proposed technologies and milestones describe the plan, not the final implementation.
> See [current architecture](../portfolio/architecture.md) and [local setup](../portfolio/local-setup.md).

==**Due Tuesday, May 26th, start of day**==

## Team 15
- Kaden Harris
- Joel deHoog
- Nathan Worth
- Chad Glazier
- Graeme Brown
- Tyson Livadney

## Teamwork Planning

- In-person meetings twice a week, scheduled after classes, and additional meetings scheduled as necessary either in-person or online.

## Unique Value Proposition

Scantron machines are constantly booked and have confusing software. What we will provide is a fast online alternative that allows professors and TAs to rapidly scan bubble sheets in bulk without needing to worry about scheduling, as well as packaging the whole system into a simple and concise interface with Canvas integration.

## Project Objectives

- Fast and reliable grading
- Canvas integration (account connection & exporting grades to assignments)
- Ambiguous & unanswered question detection
- Grading analytics
- Feedback for students
- A novel bubblesheet design

## Project Scope

#### Functional Requirements

- The system will process and grade exams in parallel.
- The system will validate users login.
- The system will flag empty and ambiguous questions for manual review.
- The system will provide data analysis to tell professors how much difficulty students had at answering each question.
- The system will allow exam grades to be exported to a Canvas assignment.
- The system will support ability to export exam results data into spreadsheets.
- The system will support multiple test versions.
- The system will automatically assign roles based on Canvas account.
- The system will notify users when batch are completed.
- The system will provide test statistics for professors.
- The system will appropriately assign partial credit
- The system will keep a log of all changes made to a graded paper.

#### Non-Functional Requirements

- The system will support 10,000 or more students.
- Students will only be able to see their own test results.
- Students can flag their exam for a manual review, if they believe something was marked incorrectly.
- The bubble sheet will have up to 100 questions.
- Batch marking jobs can be scheduled asynchronously.
- It will grade the exams substantially faster than previous iterations.
- Bubble sheet questions will have 4-5 options.

#### Technical Requirements

- Infrastructure & Deployment:
    - The system will be containerized using Docker with services defined in a Docker Compose file for local development
    - Each system component (API, worker, database, object storage, cache) will run as an isolated container
    - The system will use a reverse proxy (Nginx) to route traffic between the frontend and API

- Backend:
    - The backend API will be implemented in Python using FastAPI
    - Authentication will be handled via LTI 1.3 integration with Canvas using PyLTI1p3; no separate login system will be built
    - All API endpoints will require a valid JWT issued by the system after a successful LTI launch
    - Role-based access control will be enforced at the API layer - instructor, student, and administrator roles will have explicitly defined permissions
    - Background job processing will use ARQ with Redis as the message broker

- Image Processing:
    - Bubble detection and scoring will use OpenCV.
    - Each page of a scan will be processed as an independent job to enable parallel execution.

- Database & Storage:
    - The primary relational database will be PostgreSQL
    - Raw detected answers and instructor overrides will be stored separately to enable non-destructive re-grading
    - Images and files will never be stored in the relational database; only storage path references will be persisted

- Frontend:
    - The frontend will be implemented in Angular with TypeScript
    - Styling will use regular CSS
    - The student-facing view must be fully responsive
    - The instructor-facing view is optimized for desktop use
    - The frontend will poll job status endpoints or use WebSockets to reflect scan processing progress in real time

- Security & Privacy:
    - All data in transit will be encrypted via HTTPS/TLS
    - Student exam data will be governed by role-based access, students may only query records associated with their own account
    - Uploaded scan files will be stored encrypted at rest
    - Pre-signed URLs for file access will have a maximum expiry of a defined time window to limit unauthorized access
    - The system will comply with relevant student data privacy regulations (PIPEDA / FERPA as applicable)
    - No student personally identifiable information will be logged in application logs

- Integrations:
    - Canvas integration for authentication and role assignment
    - Grade export to Canvas will use the Canvas REST API
    - Exam result export will produce standard CSV format files

- Scalability & Maintainability:
    - The worker service will be independently scalable; additional worker containers can be added without changes to the API service
    - The answer key and grading logic will be decoupled such that re-grading an entire exam requires only enqueuing a background job, with no manual data intervention
    - The system will include a structured logging strategy that distinguishes between application events and errors, without capturing sensitive student data

#### User Requirements

- Unregistered Users
    - Can register to become either a student or a professor/TA account.
- Registered Users (both Students & Professors/TAs):
    - Can modify account details (such as name, email, password)
    - Can log in and out as necessary
- Students:
    - Can view their exam results as a side-by-side view with their uploaded bubble sheet and the system's scanned result.
    - Can request a manual review of their exam if they believe something was marked incorrectly.
    - Can view a boxplot of the overall exam statistics (similar to Canvas grade details).
- Professors & TAs:
    - Can define answer keys that the system will grade exams with.
    - Can upload scanned sheets to be marked and schedule a batch marking job.
    - Can manually change individual marks if necessary.
    - Can view and manage a list of ambiguous questions (if they are either unmarked or the system believes multiple bubbles are selected).
    - Can define rules for how partial credit is assigned.
    - Can view test analytics (grade distribution, problem questions, etc...)
    - Can manually define the end of exam questions (so that unused bubbles don't get marked as incorrect).
- Admins:
    - Can delete and view stored test results.
    - Can manage other registered users
        - Disable / Enable
        - Update
        - Delete
    - Can view performance statistics
        - Grading time to complete
        - Common grading batch sizes
        - Number of times manual intervention was required by professors or TAs
        - Site usage (total users, active users, etc.)
    - Can view in progress batch jobs 
    - Can cancel in progress batch jobs
    - Can scan documents like professors/TAs for testing purposes

## High-Level Project Description

We are building a batch optical bubble sheet marking and exam grade management system with Canvas integration. 

## High-Level Risks

- The image processing system incorrectly marking correct questions as incorrect.
- The system missing the scanning of certain questions.
- The uploaded documents not being scanned very well leading to errors during grading.
- Security concerns; we're going to be storing exams/results.
- Ensuring strict per-student viewing access (other students should NOT be able to access others' exams).
- Canvas integration, professor's will be linking their canvas accounts. The handshake between both services must be done securely. 

## High-Level Requirements and Usage Scenarios

#### Feature List

- Automatic separation of tests into different versions & grading via the corresponding answer key.
- Scheduling batch scan jobs asynchronously.
- Ambiguous and unanswered question detection.
- An explanation for the marking that students can view.
- Students can see a side-by-side view of their uploaded bubble sheet and the system's scanned result, so in case of any mistakes during scanning the student can flag their sheet for manual review.
- Grading analytics to show which questions were more difficult for students.
- Uploading an empty bubble sheet as a template which future scan jobs can reference for quicker scanning.
- Exporting grades to a Canvas assignment.
- Instructors can specify when partial credit is to be assigned. 
- Canvas LTI 1.3 authentication, users log in via Canvas. Roles (student, instructor, admin) are automatically assigned based on Canvas enrollment.
- Students can request for manual review of their exams. 
- An audit log of all changes made to an exam grade.
- Admin panel, administrators can manage users (enable/disable/delete), monitor in-progress and completed batch jobs, cancel running jobs, and view system performance statistics.

## Proposed Tech Stack

Web client - Angular LTS
Web server/auth - Fast API
Database - PostgreSQL + minIO for image storage

Web Server:
- FastAPI is simple to use and our team all has experience with it.

Web Client:
- Angular was selected, as our team is familar with similar frameworks. Additionally it has built in testing, which will allow for easier test writing.

PDF processing service:
-  The parsing and grading of bubble sheet scans will be implemented as a distinct service written in Go, using OpenCV for image processing. 
    -  OpenCV is open-source, reliable, and industry standard.
    -  Go is well-suited to handle concurrency and has bindings for OpenCV.
-  In the interim, this service will store images on the container's file system and relevant data via SQLite3. 
    -  Since the system is meant to be run locally (for now), the file system is convenient and avoids network overhead. 
    -  SQLite3 also uses the local filesystem, avoiding the cost of running an extra database container.

## Assumptions and Constraints

- Bubble sheets are properly scanned via a printer or a tool like CamScanner, meaning they are not skewed or distorted, and are of an appropriately large resolution so our system can process it accurately.
- Scanned sheets are formatted as PDFs or images (PNG, JPG, JPEG).
- Bubble sheets are of a standardized format
- Bubble sheets can have up to 100 questions.
- The student ID will be filled out correctly and correspond to a real student ID.
- Each submitted exam fits on either 1 page or 2 (if it uses one side for name + student ID like UBC exam pages do).
- Students will mark their answers with a high enough contrast color for the system to detect their answers.

## Summary Milestone Schedule

#### Project Plan

* Requirements
* User stories
* Slideshow (for video presentation)

#### Design Document & Presentation

* System Architecture Design
* Use Case Diagrams
* Database Design
* Dataflow Diagrams (Levels 0 and 1, *2 if necessary*)
* User Interface Design

#### MVP Demo
- Canvas LTI 1.3 login and automatic role assignment (student / instructor)
- Instructor can upload a batch of bubble sheet scans and trigger a grading job
- Basic bubble detection and scoring via OpenCV (single answer key, no versions)
- Ambiguous/blank question detection and flagging
- Instructor can view grading results and manually override individual marks
- Student can view their own results with a side-by-side bubble sheet comparison
- Core infrastructure running: FastAPI backend, Angular frontend, PostgreSQL, MinIO storage, all containerized via Docker Compose

#### Final Project
- All MVP features
- Partial credit rules configurable by instructor
- Student exam flagging and instructor review queue for flagged submissions
- Grading analytics dashboard (grade distribution, per-question difficulty)
- Grade export to Canvas assignment via Canvas REST API
- CSV spreadsheet export of exam results
- Batch completion notifications
- Admin panel: user management, batch job monitoring, system performance stats
- Audit log: all mark changes recorded with timestamp and actor
- Load and performance testing validating support for 10,000+ students
- End-to-end testing across all three user roles
