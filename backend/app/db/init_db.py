from app.db.session import engine
from app.db.base import Base
from app.models.job import Job
from app.models.feedback import Feedback
from app.models.result import Result


def init_db():
    Base.metadata.create_all(bind=engine)
