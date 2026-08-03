"""HTTP layer for the dashboard.

dashboard_server.py grew to ~2600 lines holding the FastAPI app, every route,
the auth dependencies and a pile of helpers. This package splits the routes into
routers by domain while dashboard_server keeps app construction, startup and the
shared helpers the routers import.
"""
