from pydantic import BaseModel, EmailStr
from schemas.auth_schema import NormalizedPersonName, NormalizedStudentNumber


class StudentCSVRow(BaseModel):
    email: EmailStr
    first_name: NormalizedPersonName
    last_name: NormalizedPersonName
    student_number: NormalizedStudentNumber
