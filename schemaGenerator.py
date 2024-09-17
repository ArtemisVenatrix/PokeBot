# this script deletes the schema in the database file and generates a new one based on the orm models in 'models.py'

import models
from sqlalchemy import create_engine

engine = create_engine("sqlite:///poke_bot.db", echo=True)

models.Base.metadata.drop_all(engine)
models.Base.metadata.create_all(engine)