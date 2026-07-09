import cadence
from cadence.contrib.google_adk.google_adk_activities import GoogleADKActivities

cadence_registry = cadence.Registry()
cadence_registry.register_activities(GoogleADKActivities())
