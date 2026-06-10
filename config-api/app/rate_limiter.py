import os
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import LoginAttempt

# Configuration parameters
MAX_ATTEMPTS = int(os.environ.get("LOGIN_MAX_ATTEMPTS", 5))
BAN_MINUTES = int(os.environ.get("LOGIN_BAN_MINUTES", 15))
WINDOW_MINUTES = int(os.environ.get("LOGIN_WINDOW_MINUTES", 10))


async def is_ip_banned(db: AsyncSession, ip_address: str) -> tuple[bool, int]:
    """
    Checks if an IP address is banned.
    Returns (banned: bool, minutes_remaining: int)
    """
    now = datetime.now(timezone.utc)
    since = now - timedelta(minutes=WINDOW_MINUTES)
    
    # Count failed attempts in the window
    q = select(func.count()).select_from(LoginAttempt).where(
        LoginAttempt.ip_address == ip_address,
        LoginAttempt.attempted_at >= since
    )
    res = await db.execute(q)
    failed_count = res.scalar() or 0
    
    if failed_count >= MAX_ATTEMPTS:
        # Find the timestamp of the last attempt to calculate ban expiration
        last_q = select(LoginAttempt.attempted_at).where(
            LoginAttempt.ip_address == ip_address
        ).order_by(LoginAttempt.attempted_at.desc()).limit(1)
        last_res = await db.execute(last_q)
        last_attempt = last_res.scalar()
        
        if last_attempt:
            if last_attempt.tzinfo is None:
                last_attempt = last_attempt.replace(tzinfo=timezone.utc)
            ban_expiry = last_attempt + timedelta(minutes=BAN_MINUTES)
            if now < ban_expiry:
                remaining = int((ban_expiry - now).total_seconds() / 60)
                return True, max(1, remaining)
            
    return False, 0


async def record_failed_attempt(db: AsyncSession, ip_address: str):
    """Record a failed login attempt and clean up entries older than 24 hours."""
    attempt = LoginAttempt(ip_address=ip_address)
    db.add(attempt)
    
    # Clean up old records (older than 24 hours) to keep table size optimized
    cutoff = datetime.now(timezone.utc) - timedelta(days=1)
    q_cleanup = delete(LoginAttempt).where(LoginAttempt.attempted_at < cutoff).execution_options(synchronize_session=False)
    
    await db.execute(q_cleanup)
    await db.commit()


async def clear_attempts(db: AsyncSession, ip_address: str):
    """Clear all failed login attempts for a given IP address upon successful login."""
    q = delete(LoginAttempt).where(LoginAttempt.ip_address == ip_address).execution_options(synchronize_session=False)
    await db.execute(q)
    await db.commit()
