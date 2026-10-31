# frozen_string_literal: true

account = Account.default

# Remove the application key created by the previous local connection flow.
DeveloperKey.where(id: 170001, account: account).find_each(&:destroy_permanently!)

def setting(name)
  ENV.fetch(name)
end

def save_if_changed(record)
  record.save! if record.new_record? || record.changed?
end

def synthetic_email(first_name, last_name)
  slug = lambda do |value|
    value.downcase.gsub(/[^a-z0-9]+/, ".").gsub(/\A\.+|\.+\z/, "")
  end
  "#{slug.call(first_name)}.#{slug.call(last_name)}@example.com"
end

def set_password(pseudonym, password)
  return if pseudonym.valid_arbitrary_credentials?(password)

  pseudonym.password = password
  pseudonym.password_confirmation = password
end

def update_admin_password(email:, password:)
  pseudonym = Account.site_admin.pseudonyms.active.find_by(unique_id: email) ||
              Account.default.pseudonyms.active.find_by(unique_id: email)
  raise "Canvas administrator #{email} does not exist" unless pseudonym

  set_password(pseudonym, password)
  save_if_changed(pseudonym)
end

def upsert_term(account:, name:, sis_id:, start_at:, end_at:)
  term = account.enrollment_terms.find_or_initialize_by(sis_source_id: sis_id)
  term.name = name
  term.start_at = start_at
  term.end_at = end_at
  term.workflow_state = "active"
  save_if_changed(term)
  term
end

def upsert_user(account:, name:, email:, sis_id:, password:)
  pseudonym = account.pseudonyms.active.find_by(unique_id: email) ||
              account.pseudonyms.active.find_by(sis_user_id: sis_id)
  user = pseudonym&.user || User.new

  user.name = name
  user.short_name = name
  user.sortable_name = name.split.reverse.join(", ")
  save_if_changed(user)
  user.register! unless user.registered?

  pseudonym ||= user.pseudonyms.build(account: account, unique_id: email)
  pseudonym.unique_id = email
  pseudonym.sis_user_id = sis_id
  pseudonym.workflow_state = "active"
  set_password(pseudonym, password)
  save_if_changed(pseudonym)

  channel = user.communication_channels.find_by(path: email) ||
            user.communication_channels.first_or_initialize
  channel.path = email
  channel.workflow_state = "active"
  save_if_changed(channel)
  user.email = channel unless user.email == email

  user
end

def activate_enrollment(course, user, type)
  enrollment = course.enrollments
                     .where(user: user, type: type)
                     .where.not(workflow_state: "deleted")
                     .first
  if enrollment
    enrollment.workflow_state = "active"
    save_if_changed(enrollment)
  else
    course.enroll_user(user, type, enrollment_state: "active")
  end
end

def upsert_course(account:, professor:, students:, term:, attributes:)
  course = account.courses.find_or_initialize_by(sis_source_id: attributes.fetch(:sis_id))
  course.name = attributes.fetch(:name)
  course.course_code = attributes.fetch(:code)
  course.enrollment_term = term
  course.workflow_state = "available"
  save_if_changed(course)

  activate_enrollment(course, professor, "TeacherEnrollment")
  course_students = attributes.fetch(:students).map { |key| students.fetch(key) }
  course_students.each do |student|
    activate_enrollment(course, student, "StudentEnrollment")
  end
  course.enrollments
        .where(type: "StudentEnrollment")
        .where.not(user_id: course_students.map(&:id))
        .where.not(workflow_state: "deleted")
        .find_each(&:destroy)

  attributes.fetch(:assignments).each do |assignment_data|
    assignment = course.assignments.where(
      title: assignment_data.fetch(:name)
    ).where.not(workflow_state: "deleted").first_or_initialize
    assignment.points_possible = assignment_data.fetch(:points)
    assignment.submission_types = "none"
    assignment.workflow_state = "published"
    save_if_changed(assignment)
  end

  course
end

calendar_year = Time.now.utc.year
update_admin_password(
  email: setting("CANVAS_LMS_ADMIN_EMAIL"),
  password: setting("CANVAS_LMS_ADMIN_PASSWORD")
)

term = upsert_term(
  account: account,
  name: "Summer Session 2",
  sis_id: "summer-session-2-#{calendar_year}",
  start_at: Time.utc(calendar_year, 7, 1),
  end_at: Time.utc(calendar_year, 8, 31, 23, 59, 59)
)

professor = upsert_user(
  account: account,
  name: setting("CANVAS_PROFESSOR_NAME"),
  email: setting("CANVAS_PROFESSOR_EMAIL"),
  sis_id: setting("CANVAS_PROFESSOR_SIS_ID"),
  password: setting("CANVAS_TEST_PASSWORD")
)

student_data = {
  maya_chen: ["Maya Chen", "maya.chen@example.com", "10000001"],
  liam_wilson: ["Liam Wilson", "liam.wilson@example.com", "10000002"],
  ava_patel: ["Ava Patel", "ava.patel@example.com", "10000003"],
  noah_kim: ["Noah Kim", "noah.kim@example.com", "10000004"],
  sofia_martinez: ["Sofia Martinez", "sofia.martinez@example.com", "10000005"],
  ethan_nguyen: ["Ethan Nguyen", "ethan.nguyen@example.com", "10000006"],
  olivia_brown: ["Olivia Brown", "olivia.brown@example.com", "10000007"],
  lucas_anderson: ["Lucas Anderson", "lucas.anderson@example.com", "10000008"],
  emma_thompson: ["Emma Thompson", "emma.thompson@example.com", "10000009"],
  jackson_lee: ["Jackson Lee", "jackson.lee@example.com", "10000010"],
  jordan_foster: ["Jordan Foster", "jordan.foster@example.com", "10000011"],
  chloe_sullivan: ["Chloe Sullivan", "chloe.sullivan@example.com", "10000012"],
  marcus_reed: ["Marcus Reed", "marcus.reed@example.com", "10000013"],
  graeme_b: ["Graeme B", "invitation.student@example.com", "33333333"]
}

# COSC 111 is the presentation-scale Canvas course. Across its 100 students,
# exactly three first names occur twice and three occur three times; the other
# 85 occur once. Every last name is unique.
presentation_first_names = %w[
  Olivia Noah Emma Liam Ava William Sophia James Isabella Benjamin
  Mia Lucas Charlotte Henry Amelia Alexander Harper Michael Evelyn Ethan
  Aaron Abigail Abraham Ada Aiden Alexandra Alexis Alyssa Andrea Angela
  Arthur Ashton Autumn Beau Bella Blake Brianna Caleb Calvin Cameron Cassandra
  Cecilia Connor Daisy Damian Delilah Derek Diana Edward Eleanor Elias Eliana
  Emily Eric Esther Finn Fiona Gavin Georgia Gianna Grant Hailey Ian Ivy Jade
  Jason Jasmine Jeremiah Jocelyn Jonah Julia Justin Katherine Kayla Kevin
  Lillian Logan Lydia Marcus Maria Melody Micah Morgan Oscar Paige Patrick
  Penelope Peter Rachel Rebecca Reese Riley Rose Samantha Simon Stella Steven
  Summer Sydney Timothy Tyler Vanessa Vivian Zachary
]
presentation_last_names = %w[
  Nguyen Smith Kim Singh Martin Johnson Lee Brown Wilson Ahmed
  Davis Clark Lewis Walker Young King Wright Scott Green Baker
  Adams Allen Alvarez Anderson Andrews Arnold Barrett Beck Benson Berry Black
  Boyd Bradley Bryant Burke Burns Burton Carlson Carr Carroll Castillo Chapman
  Chavez Christensen Crawford Cunningham Daniels Davidson Dawson Dean Dixon
  Douglas Dunn Elliott Ellis Erickson Ferguson Fields Ford Fowler Fox Gardner
  George Gibson Gilbert Gordon Grant Greene Hanson Harper Hart Hawkins Hayes
  Henry Hicks Holland Holmes Howell Hudson Hunt Hunter Jackson Jacobs Johnston
  Jones Keller Kennedy Lane Larson Lawrence Marshall Mason Matthews McCarthy
  Medina Mendoza Meyer Mills Morrison Murray Newman Nichols Palmer Porter Ramos
  Ray Rice Riley Rose Ruiz Schmidt Shaw Spencer Stone Warren Washington Weaver
  Wheeler Williamson
]

existing_names = student_data.values.map(&:first)
existing_first_names = existing_names.map { |name| name.split.first }
existing_last_names = existing_names.map { |name| name.split.last }
repeated_first_names = [
  *existing_first_names.first(3),
  *existing_first_names.slice(3, 3).flat_map { |name| [name, name] }
]
generated_count = 86
unique_first_names = presentation_first_names
                     .uniq
                     .reject { |name| existing_first_names.include?(name) }
                     .first(generated_count - repeated_first_names.length)
generated_first_names = repeated_first_names + unique_first_names
generated_last_names = presentation_last_names
                       .uniq
                       .reject { |name| existing_last_names.include?(name) }
                       .first(generated_count)
unless generated_first_names.length == generated_count &&
       generated_last_names.length == generated_count
  raise "Not enough unique presentation names"
end

(15..100).each_with_index do |number, index|
  first_name = generated_first_names[index]
  last_name = generated_last_names[index]
  student_data[:"canvas_student_#{number}"] = [
    "#{first_name} #{last_name}",
    synthetic_email(first_name, last_name),
    "20#{number.to_s.rjust(6, '0')}"
  ]
end

students = student_data.to_h do |key, (name, email, sis_id)|
  [
    key,
    upsert_user(
      account: account,
      name: name,
      email: email,
      sis_id: sis_id,
      password: setting("CANVAS_TEST_PASSWORD")
    )
  ]
end

courses = [
  {
    name: "Introduction to Programming",
    code: "COSC 111",
    sis_id: "cosc-111-001",
    students: student_data.keys,
    assignments: [
      { name: "Quiz 1", points: 20 },
      { name: "Midterm Exam", points: 100 },
      { name: "Final Exam", points: 100 }
    ]
  },
  {
    name: "Data Structures",
    code: "COSC 221",
    sis_id: "cosc-221-001",
    students: %i[
      liam_wilson ava_patel noah_kim sofia_martinez ethan_nguyen
      olivia_brown lucas_anderson emma_thompson jordan_foster chloe_sullivan
    ],
    assignments: [
      { name: "Trees and Graphs Quiz", points: 30 },
      { name: "Midterm Exam", points: 75 },
      { name: "Final Exam", points: 100 }
    ]
  },
  {
    name: "Database Systems",
    code: "COSC 304",
    sis_id: "cosc-304-001",
    students: %i[
      sofia_martinez ethan_nguyen olivia_brown lucas_anderson
      emma_thompson jackson_lee chloe_sullivan marcus_reed
    ],
    assignments: [
      { name: "SQL Quiz", points: 25 },
      { name: "Database Design Midterm", points: 80 },
      { name: "Final Exam", points: 120 }
    ]
  },
  {
    name: "Capstone Project",
    code: "COSC 499",
    sis_id: "cosc-499-001",
    students: %i[maya_chen noah_kim olivia_brown lucas_anderson jackson_lee marcus_reed],
    assignments: [
      { name: "Project Check-in", points: 10 },
      { name: "Final Presentation", points: 100 }
    ]
  }
].map do |course_data|
  upsert_course(
    account: account,
    professor: professor,
    students: students,
    term: term,
    attributes: course_data
  )
end

smoke_test_key = DeveloperKey.default
token = AccessToken.find_or_initialize_by(
  user: professor,
  developer_key: smoke_test_key,
  purpose: "Local Canvas API smoke test"
)
desired_token = setting("CANVAS_API_TOKEN")
token.token = desired_token unless token.crypted_token == AccessToken.hashed_token(desired_token)
token.workflow_state = "active"
save_if_changed(token)

assignment_count = courses.sum do |course|
  course.assignments.where.not(workflow_state: "deleted").count
end
enrollment_count = courses.sum do |course|
  course.enrollments.where.not(workflow_state: "deleted").count
end
puts "Seeded #{students.length + 1} users, #{courses.length} courses, " \
     "#{assignment_count} assignments, #{enrollment_count} enrollments, " \
     "and the professor API smoke-test token."
