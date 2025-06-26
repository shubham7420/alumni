import json
import logging
import re
import uuid
import time
import traceback
from datetime import date, datetime, timezone, timedelta
from io import BytesIO

from flask import Flask, redirect, request, jsonify, session, render_template, url_for
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import CheckConstraint
from sqlalchemy.exc import IntegrityError, ProgrammingError, SQLAlchemyError
from flask_cors import CORS
from flask_mail import Mail, Message
from werkzeug.security import generate_password_hash, check_password_hash
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from itsdangerous import URLSafeTimedSerializer
from PIL import Image
import jwt
from sqlalchemy.orm import validates



# -------------------
# Flask App Setup
# -------------------
app = Flask(__name__)
CORS(app)

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": ["http://localhost:53867"]}})  # Allow specific origin

@app.after_request
def apply_cors(response):
    response.headers.add('Access-Control-Allow-Origin', 'http://localhost:53867')  # Allow the specific origin
    response.headers.add('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type, Authorization')
    return response

app.secret_key = 'your-secret-key'  # Required for session management


# app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://postgres:Sanjana@localhost:5432/alumni_db'
# app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///mydatabase.db'  # Creates `mydatabase.db` file
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


# Password Complexity Validator
def validate_password(password):
    """Ensure the password contains at least one lowercase, one uppercase, one number, and one special character."""
    if len(password) < 8:
        return False
    if not re.search(r'[A-Z]', password):
        return False
    if not re.search(r'[a-z]', password):
        return False
    if not re.search(r'[0-9]', password):
        return False
    if not re.search(r'[@$!%*?&]', password):
        return False
    return True

# Updated parse_date function
def parse_date(date_str):
    """Parse different date formats into a timezone-aware datetime."""
    logger.info(f"Trying to parse date: {date_str}")  # Debugging log
    date_formats = [
        '%Y-%m-%dT%H:%M:%S.%f',  # Format with milliseconds
        '%Y-%m-%dT%H:%M:%SZ',    # Format without milliseconds, with 'Z'
        '%Y-%m-%d %H:%M:%S',      # Format with time, no milliseconds
        '%Y-%m-%d'                # Simple date format (YYYY-MM-DD)
    ]
    
    # Try parsing the date with each format
    for fmt in date_formats:
        try:
            parsed_date = datetime.strptime(date_str, fmt)
            # Convert to timezone-aware datetime
            return parsed_date.replace(tzinfo=timezone.utc)  # Ensure UTC timezone
        except ValueError:
            continue  # Continue to the next format if this one fails
    
    # If no format matches, raise an error
    raise ValueError(f"Date format not recognized: {date_str}")

# In-memory store for sessions (use a more persistent store like Redis in production)
active_sessions = {}

# Session timeout in seconds (15 minutes)
SESSION_TIMEOUT = 15 * 60
    


# ------------------------------------------
# ✅ Alumni Model Definition (SQLAlchemy)
# ------------------------------------------
class Alumni(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(255), nullable=False, unique=True)
    contact_number = db.Column(db.String(15), nullable=False)
    dob = db.Column(db.Date, nullable=False)
    gender = db.Column(db.String(10), nullable=False)
    course = db.Column(db.String(100), nullable=False)
    department = db.Column(db.String(100), nullable=False)
    admission_year = db.Column(db.Integer, nullable=False)
    batch_year = db.Column(db.Integer, nullable=False)
    enrollment_number = db.Column(db.String(100), nullable=False, unique=True)
    current_occupation = db.Column(db.String(255))
    current_company = db.Column(db.String(255))
    career_path = db.Column(db.String(255))
    student_package = db.Column(db.Float)  # SQLite doesn't enforce NUMERIC(15,2)
    address = db.Column(db.Text, nullable=False)
    city = db.Column(db.String(100), nullable=False)
    state = db.Column(db.String(100), nullable=False)
    country = db.Column(db.String(100), nullable=False)
    achievements = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# Create tables
with app.app_context():
    db.create_all()

# ------------------------------------------
# ✅ Create the Table in the DB
# (Runs only once at startup)
# ------------------------------------------
with app.app_context():
    db.create_all()


# --------------------------------------
# ✅ Add a New Alumni
# --------------------------------------

@app.route('/add_alumni', methods=['POST'])
def add_alumni():
    """
    Add a new alumni record:
    ✅ Validate required fields
    ✅ Validate data types & formats
    ✅ Link department & course
    ✅ Save to database
    ✅ Return JSON response
    ✅ Log full new record to console
    """
    try:
        data = request.get_json()

        # ------------------------------------
        # ✅ 1️⃣ Check required fields
        # ------------------------------------
        required_fields = [
            'full_name', 'email', 'contact_number', 'dob', 'gender',
            'course', 'department', 'admission_year', 'batch_year',
            'enrollment_number', 'address', 'city', 'state', 'country'
        ]
        missing_fields = [f for f in required_fields if not data.get(f)]
        if missing_fields:
            return jsonify({
                "status": "error",
                "message": f"Missing required fields: {', '.join(missing_fields)}",
                "data": None
            }), 400

        # ------------------------------------
        # ✅ 2️⃣ Lookup department & course
        # ------------------------------------
        dept_name = data['department'].strip()
        course_name = data['course'].strip()

        department = Department.query.filter(Department.name.ilike(dept_name)).first()
        if not department:
            return jsonify({
                "status": "error",
                "message": "Invalid department name",
                "data": None
            }), 400

        course_obj = Course.query.filter_by(department_id=department.id, name=course_name).first()
        if not course_obj:
            return jsonify({
                "status": "error",
                "message": "Invalid course for department",
                "data": None
            }), 400

        # ------------------------------------
        # ✅ 3️⃣ Validate individual fields
        # ------------------------------------

        # Email
        email = data['email'].strip()
        if '@' not in email or not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            return jsonify({
                "status": "error",
                "message": "Invalid email format",
                "data": None
            }), 400
        
                # ✅ Check if email already exists
        email = data['email'].strip()
        existing_alumni = Alumni.query.filter_by(email=email).first()
        if existing_alumni:
            return jsonify({
                "status": "error",
                "message": "Email already exists",
                "data": None
            }), 400

        # ✅ 4️⃣ Duplicate contact number check
        contact_number = data['contact_number'].strip()
        existing_contact = Alumni.query.filter_by(contact_number=contact_number).first()
        if existing_contact:
            return jsonify({
                "status": "error",
                "message": "Contact number already exists",
                "data": None
            }), 400

        # DOB
        try:
            dob = datetime.strptime(data['dob'], '%Y-%m-%d').date()
            if dob >= date.today():
                return jsonify({
                    "status": "error",
                    "message": "DOB must be a past date",
                    "data": None
                }), 400
        except ValueError:
            return jsonify({
                "status": "error",
                "message": "DOB must be in YYYY-MM-DD format",
                "data": None
            }), 400

        # Gender
        gender = data['gender'].capitalize()
        if gender not in ['Male', 'Female', 'Other']:
            return jsonify({
                "status": "error",
                "message": "Gender must be Male, Female, or Other",
                "data": None
            }), 400

        # Admission & batch year
        current_year = date.today().year
        try:
            admission_year = int(data['admission_year'])
            batch_year = int(data['batch_year'])
        except ValueError:
            return jsonify({
                "status": "error",
                "message": "Admission year and batch year must be integers",
                "data": None
            }), 400

        if not (1900 <= admission_year <= current_year):
            return jsonify({
                "status": "error",
                "message": f"Admission year must be between 1900 and {current_year}",
                "data": None
            }), 400

        if batch_year < admission_year or batch_year > current_year + 1:
            return jsonify({
                "status": "error",
                "message": "Batch year must be >= admission year and not far in the future",
                "data": None
            }), 400

        # ✅ Check if enrollment number already exists
        enrollment_number = data['enrollment_number'].strip()
        existing_enrollment = Alumni.query.filter_by(enrollment_number=enrollment_number).first()
        if existing_enrollment:
            return jsonify({
                "status": "error",
                "message": "Enrollment number already exists",
                "data": None
            }), 400


        # Student package (optional)
        student_package = data.get('student_package')
        if student_package is not None:
            try:
                student_package = float(student_package)
            except ValueError:
                return jsonify({
                    "status": "error",
                    "message": "Student package must be a valid decimal number",
                    "data": None
                }), 400

        # ------------------------------------
        # ✅ 4️⃣ Create Alumni & commit to DB
        # ------------------------------------
        new_alumni = Alumni(
            full_name=data['full_name'].strip(),
            email=email,
            contact_number=contact_number,
            dob=dob,
            gender=gender,
            department=department.name,
            course=course_obj.name,
            admission_year=admission_year,
            batch_year=batch_year,
            enrollment_number=enrollment_number,
            current_occupation=data.get('current_occupation'),
            current_company=data.get('current_company'),
            career_path=data.get('career_path'),
            student_package=student_package,
            address=data['address'].strip(),
            city=data['city'].strip(),
            state=data['state'].strip(),
            country=data['country'].strip(),
            achievements=data.get('achievements')
        )

        db.session.add(new_alumni)
        db.session.commit()

        # ------------------------------------
        # ✅ 5️⃣ Build & log response
        # ------------------------------------
        new_data = {
            "id": new_alumni.id,
            "full_name": new_alumni.full_name,
            "email": new_alumni.email,
            "contact_number": new_alumni.contact_number,
            "dob": new_alumni.dob.strftime('%Y-%m-%d'),
            "gender": new_alumni.gender,
            "department": new_alumni.department,
            "course": new_alumni.course,
            "admission_year": new_alumni.admission_year,
            "batch_year": new_alumni.batch_year,
            "enrollment_number": new_alumni.enrollment_number,
            "current_occupation": new_alumni.current_occupation,
            "current_company": new_alumni.current_company,
            "career_path": new_alumni.career_path,
            "student_package": float(new_alumni.student_package) if new_alumni.student_package is not None else None,
            "address": new_alumni.address,
            "city": new_alumni.city,
            "state": new_alumni.state,
            "country": new_alumni.country,
            "achievements": new_alumni.achievements,
            "created_at": new_alumni.created_at.strftime('%Y-%m-%d %H:%M:%S')
        }

        print(json.dumps({
            "status": "success",
            "message": "Alumni added successfully.",
            "data": new_data
        }, indent=4))

        return jsonify({
            "status": "success",
            "message": "Alumni added successfully.",
            "data": new_data
        }), 201

    except Exception as e:
        db.session.rollback()
        print(f"Error adding alumni: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Failed to add alumni: {str(e)}",
            "data": None
        }), 500


# ============================================
# ✅ Get ALL Alumni
# ============================================

@app.route('/api/alumni', methods=['GET'])
def get_all_alumni_api():
    """
    Fetch all alumni records.
    Returns a JSON list with status, message, and data.
    """
    try:
        # 1️⃣ Query all alumni
        alumni_list = Alumni.query.all()

        # 2️⃣ Format each alumni record into dictionary
        result = []
        for a in alumni_list:
            alumni_data = {
                "id": a.id,
                "full_name": a.full_name,
                "email": a.email,
                "contact_number": a.contact_number,
                "dob": a.dob.strftime('%Y-%m-%d') if a.dob else None,
                "gender": a.gender,
                "course": a.course,
                "department": a.department,
                "admission_year": a.admission_year,
                "batch_year": a.batch_year,
                "enrollment_number": a.enrollment_number,
                "current_occupation": a.current_occupation,
                "current_company": a.current_company,
                "career_path": a.career_path,
                "student_package": float(a.student_package) if a.student_package is not None else None,
                "address": a.address,
                "city": a.city,
                "state": a.state,
                "country": a.country,
                "achievements": a.achievements,
                "created_at": a.created_at.strftime('%Y-%m-%d %H:%M:%S') if a.created_at else None
            }
            result.append(alumni_data)

        # 3️⃣ Return success response
        response = {
            "status": "success",
            "message": f"Found {len(result)} alumni",
            "data": result
        }
        print(json.dumps(response, indent=4))
        return jsonify(response), 200

    except Exception as e:
        # 4️⃣ Handle unexpected errors
        print(f"Error fetching alumni: {e}")
        return jsonify({
            "status": "error",
            "message": f"Error fetching alumni: {str(e)}",
            "data": []
        }), 500


# ============================================
# ✅ Get ONE Alumni by ID
# ============================================

@app.route('/alumni/<int:alumni_id>', methods=['GET'])
def get_alumni(alumni_id):
    """
    Fetch a single alumni by ID.
    Returns JSON with status, message, and alumni data.
    """
    try:
        # 1️⃣ Query alumni by ID
        alumni = Alumni.query.get(alumni_id)

        if not alumni:
            response = {
                "status": "error",
                "message": f"Alumni with ID {alumni_id} not found.",
                "data": None
            }
            print(json.dumps(response, indent=4))
            return jsonify(response), 404

        # 2️⃣ Build response dictionary
        alumni_data = {
            "id": alumni.id,
            "full_name": alumni.full_name,
            "email": alumni.email,
            "contact_number": alumni.contact_number,
            "dob": alumni.dob.strftime('%Y-%m-%d') if alumni.dob else None,
            "gender": alumni.gender,
            "course": alumni.course,
            "department": alumni.department,
            "admission_year": alumni.admission_year,
            "batch_year": alumni.batch_year,
            "enrollment_number": alumni.enrollment_number,
            "current_occupation": alumni.current_occupation,
            "current_company": alumni.current_company,
            "career_path": alumni.career_path,
            "student_package": float(alumni.student_package) if alumni.student_package is not None else None,
            "address": alumni.address,
            "city": alumni.city,
            "state": alumni.state,
            "country": alumni.country,
            "achievements": alumni.achievements,
            "created_at": alumni.created_at.strftime('%Y-%m-%d %H:%M:%S') if alumni.created_at else None
        }

        # 3️⃣ Return success response
        response = {
            "status": "success",
            "message": "Alumni fetched successfully.",
            "data": alumni_data
        }
        print(json.dumps(response, indent=4))
        return jsonify(response), 200

    except SQLAlchemyError as e:
        # 4️⃣ Handle SQLAlchemy-specific errors
        print(f"SQLAlchemy error: {e}")
        response = {
            "status": "error",
            "message": "Database error occurred.",
            "data": None
        }
        return jsonify(response), 500

    except Exception as e:
        # 5️⃣ Handle unexpected errors
        print(f"Error: {e}")
        response = {
            "status": "error",
            "message": f"Server error: {str(e)}",
            "data": None
        }
        return jsonify(response), 500


# ------------------------
# UPDATE Alumni by ID
# ------------------------

@app.route('/update_alumni/<int:alumni_id>', methods=['PUT'])
def update_alumni(alumni_id):
    """
    Update an existing alumni record.
    Only provided fields will be updated.
    """
    alumni = Alumni.query.get(alumni_id)
    if not alumni:
        response = {
            "status": "error",
            "message": f"Alumni with ID {alumni_id} not found.",
            "data": None
        }
        print(json.dumps(response, indent=4))
        return jsonify(response), 404

    data = request.get_json()
    if not data:
        response = {
            "status": "error",
            "message": "No data provided.",
            "data": None
        }
        print(json.dumps(response, indent=4))
        return jsonify(response), 400

    # -------------------------------------
    # ✅ Update only valid, expected fields
    # -------------------------------------
    alumni.full_name = data.get('full_name', alumni.full_name)
    alumni.email = data.get('email', alumni.email)
    alumni.contact_number = data.get('contact_number', alumni.contact_number)
    alumni.gender = data.get('gender', alumni.gender)
    alumni.course = data.get('course', alumni.course)
    alumni.department = data.get('department', alumni.department)
    alumni.admission_year = data.get('admission_year', alumni.admission_year)
    alumni.batch_year = data.get('batch_year', alumni.batch_year)
    alumni.enrollment_number = data.get('enrollment_number', alumni.enrollment_number)
    alumni.current_occupation = data.get('current_occupation', alumni.current_occupation)
    alumni.current_company = data.get('current_company', alumni.current_company)
    alumni.career_path = data.get('career_path', alumni.career_path)
    alumni.address = data.get('address', alumni.address)
    alumni.city = data.get('city', alumni.city)
    alumni.state = data.get('state', alumni.state)
    alumni.country = data.get('country', alumni.country)
    alumni.achievements = data.get('achievements', alumni.achievements)

    # Optional: numeric fields with type conversion
    if 'student_package' in data:
        try:
            alumni.student_package = float(data['student_package']) if data['student_package'] is not None else None
        except ValueError:
            return jsonify({
                "status": "error",
                "message": "Invalid student_package format. Must be a number.",
                "data": None
            }), 400

    if 'dob' in data:
        try:
            alumni.dob = datetime.strptime(data['dob'], '%Y-%m-%d').date()
        except ValueError:
            return jsonify({
                "status": "error",
                "message": "Invalid dob format. Use YYYY-MM-DD.",
                "data": None
            }), 400

    # -------------------------------------
    # ✅ Commit the changes to the database
    # -------------------------------------
    try:
        db.session.commit()

        # Prepare the updated alumni data for the response
        result = {
            "id": alumni.id,
            "full_name": alumni.full_name,
            "email": alumni.email,
            "contact_number": alumni.contact_number,
            "dob": alumni.dob.strftime('%Y-%m-%d') if alumni.dob else None,
            "gender": alumni.gender,
            "course": alumni.course,
            "department": alumni.department,
            "admission_year": alumni.admission_year,
            "batch_year": alumni.batch_year,
            "enrollment_number": alumni.enrollment_number,
            "current_occupation": alumni.current_occupation,
            "current_company": alumni.current_company,
            "career_path": alumni.career_path,
            "student_package": float(alumni.student_package) if alumni.student_package is not None else None,
            "address": alumni.address,
            "city": alumni.city,
            "state": alumni.state,
            "country": alumni.country,
            "achievements": alumni.achievements,
            "created_at": alumni.created_at.strftime('%Y-%m-%d %H:%M:%S') if alumni.created_at else None
        }

        response = {
            "status": "success",
            "message": "Alumni updated successfully.",
            "data": result
        }
        print(json.dumps(response, indent=4))
        return jsonify(response), 200

    except IntegrityError:
        db.session.rollback()
        response = {
            "status": "error",
            "message": "Integrity error: duplicate or invalid value.",
            "data": None
        }
        print(json.dumps(response, indent=4))
        return jsonify(response), 400

    except Exception as e:
        db.session.rollback()
        response = {
            "status": "error",
            "message": f"Server error: {str(e)}",
            "data": None
        }
        print(json.dumps(response, indent=4))
        return jsonify(response), 500


# ------------------------
# DELETE Alumni by ID
# ------------------------

@app.route('/delete_alumni/<int:alumni_id>', methods=['DELETE'])
def delete_alumni(alumni_id):
    """
    Delete an alumni by ID.
    """
    alumni = Alumni.query.get(alumni_id)

    if not alumni:
        response = {
            "status": "error",
            "message": f"Alumni with ID {alumni_id} not found.",
            "data": None
        }
        print(json.dumps(response, indent=4))
        return jsonify(response), 404

    try:
        db.session.delete(alumni)
        db.session.commit()

        response = {
            "status": "success",
            "message": f"Alumni with ID {alumni_id} deleted successfully.",
            "data": None
        }
        print(json.dumps(response, indent=4))
        return jsonify(response), 200

    except IntegrityError:
        db.session.rollback()
        response = {
            "status": "error",
            "message": "Integrity error: This alumni cannot be deleted due to related data.",
            "data": None
        }
        print(json.dumps(response, indent=4))
        return jsonify(response), 400

    except Exception as e:
        db.session.rollback()
        response = {
            "status": "error",
            "message": f"Server error: {str(e)}",
            "data": None
        }
        print(json.dumps(response, indent=4))
        return jsonify(response), 500


# ------------------------
# Department Model
# ------------------------
class Department(db.Model):
    """
    Department table:
    - id: Primary Key
    - name: Unique department name
    - courses: Relationship to Course (one-to-many)
    """
    __tablename__ = 'departments'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)

    # One-to-Many: Department can have many Courses
    courses = db.relationship(
        'Course',
        backref='department',   # Adds `course.department` shortcut
        cascade='all, delete-orphan',  # Deletes courses if department is deleted
        lazy=True
    )

    def __repr__(self):
        return f"<Department(id={self.id}, name='{self.name}')>"


# ------------------------
# Course Model
# ------------------------
class Course(db.Model):
    """
    Course table:
    - id: Primary Key
    - department_id: Foreign Key referencing Department
    - name: Course name
    """
    __tablename__ = 'courses'

    id = db.Column(db.Integer, primary_key=True)

    # Foreign Key to Department
    department_id = db.Column(
        db.Integer,
        db.ForeignKey('departments.id', ondelete='CASCADE'),
        nullable=False
    )

    name = db.Column(db.String(100), nullable=False)

    def __repr__(self):
        return f"<Course(id={self.id}, name='{self.name}', department_id={self.department_id})>"

# -----------------------
# DEPARTMENTS CRUD
# -----------------------

# CREATE Department
@app.route('/api/departments', methods=['POST'])
def create_department():
    """Create a new department"""
    data = request.get_json()
    if not data or not data.get('name'):
        return jsonify({'error': 'Name is required'}), 400

    # Prevent duplicate
    if Department.query.filter_by(name=data['name']).first():
        return jsonify({'error': 'Department already exists'}), 400

    new_department = Department(name=data['name'])
    db.session.add(new_department)
    db.session.commit()
    return jsonify({'id': new_department.id, 'name': new_department.name}), 201

# READ ALL Departments
@app.route('/api/departments', methods=['GET'])
def get_departments():
    """Get list of all departments"""
    departments = Department.query.all()
    return jsonify([{'id': d.id, 'name': d.name} for d in departments])

# READ ONE Department by ID
@app.route('/api/departments/<int:id>', methods=['GET'])
def get_department(id):
    """Get a single department by ID"""
    department = Department.query.get_or_404(id)
    return jsonify({'id': department.id, 'name': department.name})

# UPDATE Department
@app.route('/api/departments/<int:id>', methods=['PUT'])
def update_department(id):
    """Update an existing department"""
    department = Department.query.get_or_404(id)
    data = request.get_json()
    if not data or not data.get('name'):
        return jsonify({'error': 'Name is required'}), 400

    # Prevent duplicate names
    if Department.query.filter(Department.name == data['name'], Department.id != id).first():
        return jsonify({'error': 'Another department with this name already exists'}), 400

    department.name = data['name']
    db.session.commit()
    return jsonify({'id': department.id, 'name': department.name})

# DELETE Department
@app.route('/api/departments/<int:id>', methods=['DELETE'])
def delete_department(id):
    """Delete a department by ID"""
    department = Department.query.get_or_404(id)
    db.session.delete(department)
    db.session.commit()
    return jsonify({'message': f'Department {id} deleted successfully'})


# -----------------------
# COURSES CRUD (by Department Name)
# -----------------------

# READ Courses by Department Name
@app.route('/api/departments/<string:dept_name>/courses', methods=['GET'])
def get_courses_by_department_name(dept_name):
    """Get all courses for a department (by name)"""
    department = Department.query.filter(Department.name.ilike(dept_name)).first_or_404()
    courses = Course.query.filter_by(department_id=department.id).all()

    return jsonify({
        'department': {'id': department.id, 'name': department.name},
        'courses': [{'id': c.id, 'name': c.name} for c in courses]
    })


# CREATE Course for a Department (create department if not exist)
@app.route('/api/departments/<string:dept_name>/courses', methods=['POST'])
def create_department_and_course(dept_name):
    """Create a course in a department (create department if not exist)"""
    department = Department.query.filter(Department.name.ilike(dept_name)).first()
    if not department:
        department = Department(name=dept_name)
        db.session.add(department)
        db.session.commit()

    data = request.get_json()
    if not data.get('name'):
        return jsonify({'error': 'Course name is required'}), 400

    new_course = Course(name=data['name'], department_id=department.id)
    db.session.add(new_course)
    db.session.commit()

    return jsonify({
        'message': 'Department and course created successfully',
        'department': {'id': department.id, 'name': department.name},
        'course': {'id': new_course.id, 'name': new_course.name}
    }), 201


# UPDATE Course in Department
@app.route('/api/departments/<string:dept_name>/courses/<int:course_id>', methods=['PUT'])
def update_course_in_department(dept_name, course_id):
    """Update a course inside a department (by department name & course ID)"""
    department = Department.query.filter(Department.name.ilike(dept_name)).first_or_404()
    course = Course.query.filter_by(id=course_id, department_id=department.id).first_or_404()

    data = request.get_json()
    if not data.get('name'):
        return jsonify({'error': 'New course name is required'}), 400

    course.name = data['name']
    db.session.commit()

    return jsonify({
        'message': 'Course updated successfully',
        'course': {'id': course.id, 'name': course.name}
    })


# DELETE Course (by ID)
@app.route('/api/courses/<int:course_id>', methods=['DELETE'])
def delete_course(course_id):
    """Delete a course by its ID"""
    course = Course.query.get_or_404(course_id)
    db.session.delete(course)
    db.session.commit()

    return jsonify({'message': 'Course deleted successfully'})






class CollegeAdmin(db.Model):
    __tablename__ = 'college'

    id = db.Column(db.Integer, primary_key=True)
    college_name = db.Column(db.String(255), nullable=False)
    username = db.Column(db.String(255), nullable=False, unique=True)
    contact_number = db.Column(db.String(20), nullable=False, unique=True)
    email = db.Column(db.String(255))
    address = db.Column(db.String(255))
    city = db.Column(db.String(255))
    state = db.Column(db.String(255))
    country = db.Column(db.String(255))
    password_hash = db.Column(db.String(255), nullable=False)
    auth_token = db.Column(db.String(512))


# ----------------------------------------
# ✅ Register a New College Admin (full structure like add_alumni)
# ----------------------------------------
@app.route('/register_college', methods=['POST'])
def register_college():
    """
    Register a new college admin:
    ✅ Validate required fields
    ✅ Validate unique username, email, contact number
    ✅ Hash password securely
    ✅ Save to DB
    ✅ Return clean JSON response
    ✅ Log full new record
    """
    try:
        data = request.get_json()
        logger.info(f"Received college registration data: {data}")

        # ----------------------------------------
        # ✅ 1️⃣ Check required fields
        # ----------------------------------------
        required_fields = ['college_name', 'username', 'password', 'email', 'contact_number', 'address', 'city', 'state', 'country']

        missing_fields = [f for f in required_fields if not data.get(f)]
        if missing_fields:
            return jsonify({
                "status": "error",
                "message": f"Missing required fields: {', '.join(missing_fields)}",
                "data": None
            }), 400

        # ----------------------------------------
        # ✅ 2️⃣ Validate unique username, email, contact number
        # ----------------------------------------
        username = data['username'].strip()
        if CollegeAdmin.query.filter_by(username=username).first():
            return jsonify({
                "status": "error",
                "message": "Username already exists",
                "data": None
            }), 400

        email = data['email'].strip()
        if CollegeAdmin.query.filter_by(email=email).first():
            return jsonify({
                "status": "error",
                "message": "Email already exists",
                "data": None
            }), 400

        contact_number = data['contact_number'].strip()
        if CollegeAdmin.query.filter_by(contact_number=contact_number).first():
            return jsonify({
                "status": "error",
                "message": "Contact number already exists",
                "data": None
            }), 400

        # ----------------------------------------
        # ✅ 3️⃣ Hash password
        # ----------------------------------------
        password_hash = generate_password_hash(data['password'])

        # ----------------------------------------
        # ✅ 4️⃣ Create CollegeAdmin & commit to DB
        # ----------------------------------------
        new_college = CollegeAdmin(
            college_name=data['college_name'].strip(),
            username=username,
            password_hash=password_hash,
            email=email,
            contact_number=contact_number,
            address=data['address'].strip(),
            city=data['city'].strip(),
            state=data['state'].strip(),
            country=data['country'].strip()
        )

        db.session.add(new_college)
        db.session.commit()

        # ----------------------------------------
        # ✅ 5️⃣ Build & log response
        # ----------------------------------------
        new_data = {
            "id": new_college.id,
            "college_name": new_college.college_name,
            "username": new_college.username,
            "email": new_college.email,
            "contact_number": new_college.contact_number,
            "address": new_college.address,
            "city": new_college.city,
            "state": new_college.state,
            "country": new_college.country
        }

        logger.info(json.dumps({
            "status": "success",
            "message": "College registered successfully.",
            "data": new_data
        }, indent=4))

        return jsonify({
            "status": "success",
            "message": "College registered successfully.",
            "data": new_data
        }), 201

    except Exception as e:
        db.session.rollback()
        logger.exception("Error registering college")
        return jsonify({
            "status": "error",
            "message": f"Failed to register college: {str(e)}",
            "data": None
        }), 500

# -------------------------------
# ✅ JWT Generator Helper
# -------------------------------
def generate_jwt_token(admin):
    payload = {
        'username': admin.username,
        'exp': datetime.utcnow() + timedelta(hours=1)
    }
    return jwt.encode(payload, app.config['SECRET_KEY'], algorithm='HS256')

# -------------------------------
# ✅ Admin Login
# -------------------------------
@app.route('/admin_login', methods=['POST'])
def admin_login():
    try:
        data = request.get_json()
        logger.info("Received college admin login data: %s", json.dumps(data, indent=4))

        required_fields = ['username_or_contact_number', 'password']
        missing_fields = [field for field in required_fields if field not in data]
        if missing_fields:
            return jsonify({"error": f"Missing required fields: {', '.join(missing_fields)}"}), 400

        identifier = data['username_or_contact_number']
        admin = CollegeAdmin.query.filter(
            (CollegeAdmin.username == identifier) |
            (CollegeAdmin.contact_number == identifier)
        ).first()

        if not admin:
            return jsonify({"error": "Invalid username or contact number"}), 401

        if not check_password_hash(admin.password_hash, data['password']):
            return jsonify({"error": "Invalid password"}), 401

        auth_token = generate_jwt_token(admin)
        admin.auth_token = auth_token
        db.session.commit()

        session['session_id'] = str(uuid.uuid4())
        session['last_activity'] = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')

        success_msg = {
            "message": "Login successful",
            "auth_token": auth_token,
            "session_id": session['session_id'],
            "college_admin": {
                "username": admin.username,
                "contact_number": admin.contact_number,
                "college_name": admin.college_name
            }
        }
        logger.info("Response: %s", json.dumps(success_msg, indent=4))
        return jsonify(success_msg), 200

    except Exception as e:
        logger.error("Error during login: %s", str(e))
        logger.error(traceback.format_exc())
        return jsonify({"error": "An unexpected error occurred during login"}), 500

# # -------------------------------
# # ✅ Session Timeout Check (15 min)
# # -------------------------------
# @app.before_request
# def check_session_timeout():
#     # ✅ Allow these routes without session:
#     allowed_paths = [
#         'admin_login', 'admin_login_page',
#         'logout', 'static',
#         'admin_registration_page'
#     ]

#     if request.endpoint in allowed_paths:
#         return  # skip check

#     last_activity = session.get('last_activity')
#     if last_activity:
#         last_activity_dt = datetime.strptime(last_activity, '%Y-%m-%d %H:%M:%S')
#         now = datetime.utcnow()
#         if now - last_activity_dt > timedelta(minutes=15):
#             session.clear()
#             # ✅ redirect instead of JSON
#             return redirect(url_for('admin_login_page'))
#         else:
#             session['last_activity'] = now.strftime('%Y-%m-%d %H:%M:%S')
#     else:
#         # ✅ if no session at all, redirect to login
#         return redirect(url_for('admin_login_page'))



@app.route('/analytics')
def admin_analytics():
    alumni = Alumni.query.all()
    data = []
    for a in alumni:
        data.append({
            "id": a.id,
            "full_name": a.full_name,
            "email": a.email,
            "contact_number": a.contact_number,
            "dob": a.dob.strftime('%Y-%m-%d') if a.dob else None,
            "gender": a.gender,
            "course": a.course,
            "department": a.department,
            "admission_year": a.admission_year,
            "batch_year": a.batch_year,
            "enrollment_number": a.enrollment_number,
            "current_occupation": a.current_occupation,
            "current_company": a.current_company,
            "career_path": a.career_path,
            "student_package": float(a.student_package) if a.student_package is not None else None,
            "address": a.address,
            "city": a.city,
            "state": a.state,
            "country": a.country,
            "achievements": a.achievements,
            "created_at": a.created_at.strftime('%Y-%m-%d %H:%M:%S') if a.created_at else None
        })
    return render_template('analytics.html', alumni_data=data)

# ------------------------
# ✅ Static HTML routes
# ------------------------

@app.route('/')
@app.route('/index')
def index_page():
    return render_template('index.html')


@app.route('/admin_login')
def admin_login_page():
    return render_template('admin_login.html')

@app.route('/admin_registration')
def admin_registration_page():
    return render_template('admin_registration.html')

@app.route('/analytics')
def analytics_page():
    return render_template('analytics.html')

@app.route('/create_alumni')
def create_alumni_page():
    return render_template('create_alumni.html')

@app.route('/all_alumni')
def all_alumni_page():
    # ✅ OPTIONAL: Fetch data and render if you want dynamic content:
    try:
        alumni_list = Alumni.query.all()
        return render_template('all_alumni.html', alumni_data=alumni_list)
    except Exception as e:
        logger.exception("Error rendering alumni page")
        return f"Error: {str(e)}", 500

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('admin_login_page'))



# -------------------
# Run the App
# -------------------
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
