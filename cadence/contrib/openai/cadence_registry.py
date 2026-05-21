import cadence
from cadence.contrib.openai import OpenAIActivities


cadence_registry = cadence.Registry()
cadence_registry.register_activities(OpenAIActivities())
