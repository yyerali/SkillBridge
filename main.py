import json
from flask import Flask, render_template, request, redirect, url_for, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from openai import OpenAI

client = OpenAI(
    base_url="https://api.groq.com/openai/v1",
    api_key="########"
)

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret123'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///app.db'
db = SQLAlchemy(app)

course_material = db.Table('course_material',
    db.Column('course_id', db.Integer, db.ForeignKey('course.id')),
    db.Column('material_id', db.Integer, db.ForeignKey('material.id'))
)

class Material(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100))
    content = db.Column(db.Text)
    unit = db.Column(db.Integer)

class Course(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer)
    materials = db.relationship('Material', secondary=course_material)

class Progress(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer)
    material_id = db.Column(db.Integer)
    completed = db.Column(db.Boolean, default=False)

class Question(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    text = db.Column(db.Text)
    option_a = db.Column(db.String(200))
    option_b = db.Column(db.String(200))
    option_c = db.Column(db.String(200))
    option_d = db.Column(db.String(200))
    correct = db.Column(db.String(1))
    material_id = db.Column(db.Integer)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    email = db.Column(db.String(120), unique=True)
    password = db.Column(db.String(200))
    role = db.Column(db.String(20))
    school = db.Column(db.String(100))
    grade = db.Column(db.String(10))
    teacher_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    students = db.relationship('User', backref=db.backref('teacher', remote_side=[id]))

def is_teacher():
    if 'user_id' not in session:
        return False
    user = User.query.get(session['user_id'])
    return user.role == "teacher"

@app.route('/teacher/assign_course/<int:student_id>', methods=['GET', 'POST'])
def assign_course(student_id):
    if not is_teacher(): return "Access Denied"
    student = User.query.get_or_404(student_id)
    subjects = sorted([
        'AP CS A',
        'CS AS Level',
        'Further Mathematics A',
        'AP Calculus BC',
        'AP Calculus AB',
        'AP Precalculus',
        'AP Statistics',
        'AP Chemistry',
        'AP Physics 1',
        'A Level Biology',
        'AP Physics 2',
        'AP Electromagnetism',
        'AP Microeconomics',
        'AP Macroeconomics',
        'Business A',
        'A Level History',
        'AP English Language'
    ])

    if request.method == 'POST':
        selected_subjects = request.form.getlist("selected_subjects")
        
        materials = []
        for subject in selected_subjects:
            unit_val = request.form.get(f"unit_{subject}", type=int, default=1)
            content = generate_lesson(f"{subject} Unit {unit_val} syllabus concepts", unit_val)
            
            m = Material(title=subject, content=content, unit=unit_val)
            db.session.add(m)
            db.session.flush() 
            
            materials.append(m)
            db.session.add(Progress(user_id=student.id, material_id=m.id))
            generate_questions(content, m.id)
            
        course = Course(user_id=student.id)
        course.materials = materials
        db.session.add(course)
        db.session.commit()
        return redirect('/teacher/dashboard')
    
    return render_template('assign_course.html', student=student, subjects=subjects)

def generate_lesson(topic, unit):
    prompt = (
        f"Act as an expert teacher explaining '{topic}' for Unit {unit} at an AP/A-Level standard. "
        "Do NOT write an introduction or label sections. Do NOT use headings or structured formatting. "
        "Focus on actually explaining the topic in depth as if teaching a student who needs to truly understand it. "
        "Start directly with the core idea and build understanding step by step. "
        "Explain the underlying principles, how things work, and why they work that way. "
        "When introducing a concept, break it down clearly and connect it to prior knowledge. "
        "Use analogies only when they genuinely help understanding, not as decoration. "
        "Include concrete examples naturally within the explanation instead of separating them out. "
        "Avoid vague summaries, bullet points, or high-level overviews. "
        "Prioritize clarity, depth, and precise reasoning so the student could apply the concept in an exam."
        "Use 5 examples to demonstrate and teach the topic at hand. Make sure to add exam prep questions as well."
    )
    try:
        res = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}]
        )
        return res.choices[0].message.content
    except Exception as e:
        return f"Error generating content: {str(e)}"

def generate_questions(content, material_id):
    try:
        res = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": "You are a strict exam question generator. Output ONLY raw JSON."
                },
                {
                    "role": "user",
                    "content": (
                        "Using ONLY the lesson below, generate 10 high-quality multiple choice questions. "
                        "Each question must test understanding of the explanations in the lesson. "
                        "Do NOT use outside knowledge.\n\n"
                        "Lesson:\n"
                        f"{content}\n\n"
                        "Format strictly as JSON:\n"
                        "[{\"question\":\"...\",\"A\":\"...\",\"B\":\"...\",\"C\":\"...\",\"D\":\"...\",\"correct\":\"A\"}]"
                    )
                }
            ]
        )

        txt = res.choices[0].message.content.strip()

        if "```" in txt:
            txt = txt.split("```")[1].replace("json", "").strip()

        questions_data = json.loads(txt)

        for q_data in questions_data:
            db.session.add(Question(
                text=q_data['question'],
                option_a=q_data['A'],
                option_b=q_data['B'],
                option_c=q_data['C'],
                option_d=q_data['D'],
                correct=q_data['correct'].upper(),
                material_id=material_id
            ))

        db.session.commit()
        return True

    except Exception as e:
        print(f"Question Gen Error: {e}")
        return False

with app.app_context():
    db.create_all()

@app.route('/register', methods=['GET','POST'])
@app.route('/', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        role = request.form['role']

        user = User(
            name=request.form['name'],
            email=request.form['email'],
            password=generate_password_hash(request.form['password']),
            role=role,
            school=request.form.get('school'),
            grade=request.form.get('grade')
        )

        if role == "student":
            t = request.form.get('teacher_id')
            if t:
                user.teacher_id = int(t)

        if role == "teacher":
            if request.form.get("teacher_code") != "Q03092021Q":
                return "wrong code"

        db.session.add(user)
        db.session.commit()
        return redirect('/login')

    teachers = User.query.filter_by(role="teacher").all()
    return render_template('register.html', teachers=teachers)

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(email=request.form['email']).first()
        if user and check_password_hash(user.password, request.form['password']):
            session['user_id'] = user.id
            return redirect('/teacher/dashboard' if user.role=="teacher" else '/dashboard')

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect('/login')

    uid = session['user_id']
    courses = Course.query.filter_by(user_id=uid).all()
    progress = Progress.query.filter_by(user_id=uid).all()

    done = len([p for p in progress if p.completed])
    total = len(progress)
    percent = int((done/total)*100) if total else 0

    return render_template('dashboard.html', courses=courses, percent=percent)

@app.route('/test/<int:material_id>', methods=['GET','POST'])
def test(material_id):
    material = Material.query.get_or_404(material_id)
    questions = Question.query.filter_by(material_id=material_id).all()

    if request.method == 'POST':
        score = 0

        for q in questions:
            if request.form.get(str(q.id)) == q.correct:
                score += 1

        percent = int(score/len(questions)*100)

        if percent >= 60:
            p = Progress.query.filter_by(
                user_id=session['user_id'],
                material_id=material_id
            ).first()
            if p:
                p.completed = True
                db.session.commit()

        return render_template('result.html', percent=percent)

    return render_template('test.html', questions=questions, material=material)

@app.route('/teacher/dashboard')
def teacher_dashboard():
    if not is_teacher():
        return redirect('/login')

    teacher = User.query.get(session['user_id'])
    students = User.query.filter_by(teacher_id=teacher.id).all()

    return render_template('teacher_dashboard.html', students=students)

@app.route('/teacher/add_student', methods=['POST'])
def add_student():
    student = User(
        name=request.form['name'],
        email=request.form['email'],
        password=generate_password_hash("1234"),
        role="student",
        school=request.form['school'],
        grade=request.form['grade'],
        teacher_id=session['user_id']
    )
    db.session.add(student)
    db.session.commit()
    return redirect('/teacher/dashboard')

if __name__ == "__main__":
    app.run(debug=True)