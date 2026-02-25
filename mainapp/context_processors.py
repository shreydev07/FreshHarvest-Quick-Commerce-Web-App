from .models import UserInfo

def user_context(request):
    """
    Adds 'userid' (from session), 'username' and 'profile_url' to templates.
    Uses admin avatar fallback when user.profile is not set.
    """
    ctx = {}
    userid = request.session.get('userid')
    ctx['userid'] = userid
    ctx['username'] = None
    ctx['profile_url'] = None
    if not userid:
        return ctx

    try:
        user = UserInfo.objects.filter(email=userid).first()
        if not user:
            return ctx
        ctx['name'] = user.name or getattr(user, 'name', None) or userid
        if getattr(user, 'profile', None):
            try:
                ctx['profile_url'] = user.profile.url
            except Exception:
                ctx['profile_url'] = user.profile
        else:
            # admin avatar fallback used in adminapp templates
            ctx['profile_url'] = '/static/admin/assets/images/user/avatar-2.jpg'
    except Exception:
        pass
    return ctx