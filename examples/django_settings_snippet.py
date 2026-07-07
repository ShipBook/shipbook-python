"""Django wiring for Shipbook.

In your Django project's ``settings.py``:

    import logging
    import os
    import shipbook

    shipbook.start(
        app_id=os.environ["SHIPBOOK_APP_ID"],
        app_key=os.environ["SHIPBOOK_APP_KEY"],
        capture_level=logging.INFO,
    )

    MIDDLEWARE = [
        # ... your other middleware ...
        "shipbook.integrations.django.ShipbookMiddleware",
    ]

To attach the authenticated user, subclass the middleware:

    from shipbook import User
    from shipbook.integrations.django import ShipbookMiddleware as _Base

    class ShipbookMiddleware(_Base):
        def get_user(self, request):
            if request.user.is_authenticated:
                return User(user_id=str(request.user.pk), email=request.user.email)
            return None

and reference your subclass path in ``MIDDLEWARE`` instead.
"""
