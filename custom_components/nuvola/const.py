DOMAIN = "nuvola"
NAME = "Nuvola Madisoft"
BASE_URL = "https://nuvola.madisoft.it"
API_BASE = BASE_URL + "/api-studente/v1"

CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_STUDENT_IDS = "student_ids"
CONF_STUDENT_ID = "student_id"  # legacy key for migration
CONF_STUDENT_NAME = "student_name"  # legacy key for migration

MAX_STUDENTS = 5
UPDATE_INTERVAL_MINUTES = 10
REQUEST_TIMEOUT = 30
COMPITI_DAYS = 14

PLATFORMS = ["sensor", "binary_sensor", "calendar"]

ATTR_STUDENT_ID = "student_id"
ATTR_STUDENT_NAME = "student_name"
ATTR_CLASS = "classe"
ATTR_SCHOOL = "scuola"
ATTR_PERIOD = "periodo"
ATTR_VOTES = "voti"
ATTR_SUBJECTS = "materie"
ATTR_HOMEWORK = "compiti"
ATTR_ABSENCES = "assenze"
ATTR_NOTES = "note"
ATTR_EVENTS = "eventi"
ATTR_LESSONS = "lezioni"
