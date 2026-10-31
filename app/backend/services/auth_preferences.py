"""Persistence for a user's account notification preferences."""


async def update_notification_preferences(db, user, request):
    try:
        user.email_notifications_enabled = request.email_notifications_enabled
        user.regrade_alerts_enabled = request.regrade_alerts_enabled
        user.batch_job_complete_enabled = request.batch_job_complete_enabled
        await db.commit()
        await db.refresh(user)
    except Exception:
        await db.rollback()
        raise

    return user
