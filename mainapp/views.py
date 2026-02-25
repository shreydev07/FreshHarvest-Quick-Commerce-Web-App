from django.shortcuts import render, redirect,get_object_or_404
from . models import *
from django.contrib import messages
from adminapp.models import Product as AdminProduct, OfferItem, get_active_offer_price, Offer, Category
import requests
from django.conf import settings
from django.http import JsonResponse
from django.db.models import Q
from django.db import transaction
from django.utils import timezone  # new import
from decimal import Decimal
from django.template.loader import render_to_string
from django.core.mail import EmailMultiAlternatives
from django.utils.html import strip_tags
from django.urls import reverse

# Create your views here.
def index(request):
    from adminapp.models import Offer  # ensure import
    now = timezone.now()
    active_offers = Offer.objects.filter(
        active=True,
        start_datetime__lte=now,
        end_datetime__gte=now
    ).order_by('-start_datetime')
    context= {
        'userid' : request.session.get('userid'),
        'products' : AdminProduct.objects.all(),
        'new_arrivals' : AdminProduct.objects.all()[:10],
        'categories': Category.objects.order_by('name'),
        'active_offers': active_offers,  # <-- add this
    }
    return render(request, 'index.html', context)

def products(request):
    q = request.GET.get('q', '') or ''
    q = q.strip()
    category_id = request.GET.get('category', '') or ''
    category_id = category_id.strip()

    qs = AdminProduct.objects.all()
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(description__icontains=q) | Q(category__name__icontains=q))
    if category_id:
        try:
            qs = qs.filter(category__id=int(category_id))
        except (ValueError, TypeError):
            pass

    vegetables = AdminProduct.objects.filter(category__name__iexact="Vegetables")
    fruits = AdminProduct.objects.filter(category__name__iexact="Fruits")

    # default: gather currently active offer items (existing behavior)
    now = timezone.now()
    active_offer_items = OfferItem.objects.select_related('product', 'offer').filter(
        unlisted=False,
        offer__active=True,
        offer__start_datetime__lte=now,
        offer__end_datetime__gte=now
    ).order_by('-offer__start_datetime')

    offer_map = {}
    offer_items_list = []
    for oi in active_offer_items:
        pid = oi.product_id
        if pid not in offer_map:
            offer_map[pid] = {
                'offer_price': oi.offer_price,
                'offer_id': oi.offer_id,
                'offer_item_id': oi.id,
                'offer_title': oi.offer.title
            }
        offer_items_list.append({'product': oi.product, 'offer_price': oi.offer_price, 'offer_item_id': oi.id, 'offer': oi.offer})

    # ---- NEW: if ?offer=<id> is present, show only that offer's items ----
    selected_offer = None
    offer_param = request.GET.get('offer')
    if offer_param:
        try:
            offer_id = int(offer_param)
            selected_offer = Offer.objects.filter(pk=offer_id).first()
            if selected_offer:
                # show items for the selected offer (regardless of active state)
                selected_items_qs = OfferItem.objects.select_related('product').filter(
                    offer=selected_offer,
                    unlisted=False
                ).order_by('id')
                # rebuild offer_map and offer_items_list to only include these items
                offer_map = {}
                offer_items_list = []
                for oi in selected_items_qs:
                    pid = oi.product_id
                    offer_map[pid] = {
                        'offer_price': oi.offer_price,
                        'offer_id': oi.offer_id,
                        'offer_item_id': oi.id,
                        'offer_title': oi.offer.title
                    }
                    offer_items_list.append({'product': oi.product, 'offer_price': oi.offer_price, 'offer_item_id': oi.id, 'offer': oi.offer})
        except (ValueError, TypeError):
            selected_offer = None
    # ---- end new ----

    context = {
        'userid': request.session.get('userid'),
        'products': qs,
        'vegetables': vegetables,
        'fruits': fruits,
        'q': q,
        'category_id': category_id,
        'offer_items_list': offer_items_list,
        'offer_map': offer_map,
        'selected_offer': selected_offer,  # template can use this if present
    }
    # after building context, annotate boolean for template
    for p in qs:
        p.is_out_of_stock = (p.stock is None) or (p.stock <= Decimal('0'))
    context['products'] = qs
    return render(request, 'products.html', context)


    
def about(request):
    context= {
        'userid' : request.session.get('userid'),
    }
    return render(request, 'about.html',context)

def contact(request):
    context= {
        'userid' : request.session.get('userid'),
    }
    if request.method == 'POST':
        name = request.POST.get('name')
        email = request.POST.get('email')
        contactno = request.POST.get('contactno')
        subject = request.POST.get('subject')
        message = request.POST.get('message')
        enq = Enquiry(name=name, email=email, contactno=contactno, subject=subject, message=message)
        enq.save()

        url = "http://sms.bulkssms.com/submitsms.jsp"
        params = {
            "user": "BRIJESH",
            "key": "066c862acdXX",
            "mobile": f"{contactno}",
            "message": "Thanks for enquiry we will contact you soon.\n\n-Bulk SMS",
            "senderid": "UPDSMS",
            "accusage": "1",
            "entityid": "1201159543060917386",
            "tempid": "1207169476099469445"
        }

        response = requests.get(url, params=params)
        print("Response:", response.text)
        messages.success(request,"Your enquiry has been submitted successfully.")
        return redirect('contact')
    return render(request, 'contact.html',context)

def login(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        try:
            user = LoginInfo.objects.get(usertype="user",username=username,password=password)
            if user is not None:
                request.session['userid'] = username
                messages.success(request,"Welcome User")
                return redirect('index')
        except LoginInfo.DoesNotExist:
            messages.error(request,"Invalid username or password")
            return redirect('login')
    return render(request, 'login.html')

# ...existing code...
def register(request):
    # pass site key to template
    site_key = getattr(settings, 'RECAPTCHA_SITE_KEY', '')

    if request.method == 'POST':
        name = request.POST.get('name','').strip()
        email = request.POST.get('email','').strip()
        contactno = request.POST.get('contactno','').strip()
        password = request.POST.get('password','')
        cpassword = request.POST.get('cpassword','')

        # basic server-side validation (mirror client)
        if password != cpassword:
            messages.error(request, "Password and Confirm Password should be same.")
            return render(request, 'register.html', {'RECAPTCHA_SITE_KEY': site_key})
        if len(password) < 8:
            messages.error(request, "Password must be at least 8 characters.")
            return render(request, 'register.html', {'RECAPTCHA_SITE_KEY': site_key})
        contact_digits = ''.join(ch for ch in contactno if ch.isdigit())
        if len(contact_digits) < 10:
            messages.error(request, "Phone number must be at least 10 digits.")
            return render(request, 'register.html', {'RECAPTCHA_SITE_KEY': site_key})

        # verify google reCAPTCHA v2 server-side
        recaptcha_response = request.POST.get('g-recaptcha-response','').strip()
        # prefer common name used in many projects, fall back to other
        secret = getattr(settings, 'RECAPTCHA_SECRET_KEY', '') or getattr(settings, 'RECAPTCHA_SECRET', '')

        # If secret missing allow bypass in DEBUG to avoid blocking local development.
        if not secret:
            if not getattr(settings, 'DEBUG', False):
                messages.error(request, "Captcha verification failed (server misconfiguration). Contact admin.")
                return render(request, 'register.html', {'RECAPTCHA_SITE_KEY': site_key})
            # DEBUG mode without secret -> skip verification but log a warning
        else:
            # secret present -> require user to have completed captcha
            if not recaptcha_response:
                messages.error(request, "Captcha verification failed. Please tick the captcha box.")
                return render(request, 'register.html', {'RECAPTCHA_SITE_KEY': site_key})
            verify_url = 'https://www.google.com/recaptcha/api/siteverify'
            try:
                resp = requests.post(verify_url, data={
                    'secret': secret,
                    'response': recaptcha_response,
                    'remoteip': request.META.get('REMOTE_ADDR','')
                }, timeout=5)
                result = resp.json()
            except requests.RequestException:
                messages.error(request, "Captcha verification request failed. Try again.")
                return render(request, 'register.html', {'RECAPTCHA_SITE_KEY': site_key})

            if not result.get('success'):
                messages.error(request, "Captcha verification failed. Please tick the captcha box.")
                return render(request, 'register.html', {'RECAPTCHA_SITE_KEY': site_key})

        # email uniqueness check
        if LoginInfo.objects.filter(username=email).exists():
            messages.error(request, "Email already exists.")
            return render(request, 'register.html', {'RECAPTCHA_SITE_KEY': site_key})

        # create user (save login first to ensure FK integrity)
        try:
            with transaction.atomic():
                log = LoginInfo(usertype="user", username=email, password=password)
                log.save()
                user = UserInfo(name=name, email=email, contactno=contactno, login=log)
                user.save()
        except Exception as e:
            messages.error(request, "Registration failed. Try again.")
            return render(request, 'register.html', {'RECAPTCHA_SITE_KEY': site_key})

        messages.success(request, "Registration is done successfully. Please login.")
        return redirect('login')

    return render(request, 'register.html', {'RECAPTCHA_SITE_KEY': site_key})
# ...existing code...

def adminlogin(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        try:
            ad = LoginInfo.objects.get(username=username, password=password)
            if ad is not None:
                request.session['adminid'] = username
                messages.success(request,"Welcome Admin")
                return redirect('admindash')
        except LoginInfo.DoesNotExist:
            messages.error(request,"Invalid Username or password")
            return redirect('adminlogin')
    return render(request, 'adminlogin.html')


def product_details(request, id):
    product = get_object_or_404(AdminProduct, pk=id)

    # compute effective price using existing helper (returns (price, offer_or_None))
    try:
        effective_price, active_offer = get_active_offer_price(product)
    except Exception:
        effective_price = product.price if getattr(product, 'price', None) is not None else 0

    # ...existing context population...
    context = {
        'userid': request.session.get('userid'),
        'product': product,
        'effective_price': effective_price,
    }

    return render(request, 'product_details.html', context)

def product_search(request):
    query = request.GET.get('q', '')
    results = []
    if query:
        products = AdminProduct.objects.filter(Q(title__icontains=query) | Q(description__icontains=query))[:10]
        for p in products:
            price, oi = get_active_offer_price(p)
            results.append({
                'id': p.id,
                'title': p.title,
                'image': p.cover_image.url if p.cover_image else '',
                'price': str(price),
                'unit': str(p.unit.name) if p.unit else '',
                'in_offer': True if oi else False
            })
    return JsonResponse({'results': results})
def tem(requests):
    return render(requests, 'tem.html')


def subscribe(request):
    if request.method == 'POST':
        email = request.POST.get('email', '').strip()
        from django.core.validators import validate_email
        from django.core.exceptions import ValidationError

        if not email:
            messages.error(request, 'Please enter an email address to subscribe.')
            return redirect('index')

        # validate format server-side
        try:
            validate_email(email)
        except ValidationError:
            messages.error(request, 'Please enter a valid email address.')
            return redirect('index')

        # check existing (case-insensitive)
        if Subscriber.objects.filter(email__iexact=email).exists():
            messages.info(request, 'This email is already subscribed.')
            return redirect('index')

        try:
            Subscriber.objects.create(email=email)

            # prepare email template context
            subscriber_name = email.split('@')[0].replace('.', ' ').title()
            cta_link = request.build_absolute_uri('/')
            your_brand_name = getattr(settings, 'BRAND_NAME', 'FreshHarvest')
            year = timezone.now().year
            try:
                unsubscribe_link = request.build_absolute_uri(reverse('unsubscribe'))
            except Exception:
                unsubscribe_link = request.build_absolute_uri('/')

            tpl_ctx = {
                'subscriber_name': subscriber_name,
                'cta_link': cta_link,
                'your_brand_name': your_brand_name,
                'year': year,
                'unsubscribe_link': unsubscribe_link,
            }

            # render HTML and plain-text fallback
            html_content = render_to_string('email_template.html', tpl_ctx)
            text_content = strip_tags(html_content)

            subject = f"Welcome to {your_brand_name} — Thanks for subscribing"
            from_email = 'FreshHarvest Team' if getattr(settings, 'EMAIL_HOST_USER', None) else None

            try:
                msg = EmailMultiAlternatives(subject=subject, body=text_content, from_email=from_email, to=[email])
                msg.attach_alternative(html_content, "text/html")
                msg.send()
                messages.success(request, 'Thanks — you have been subscribed. A confirmation email has been sent.')
            except Exception:
                # subscription succeeded but email failed
                messages.warning(request, 'Subscribed successfully, but we could not send the confirmation email right now.')

        except Exception:
            messages.error(request, 'Subscription failed. Please try again later.')

        return redirect('index')
    # for non-POST (e.g., API callers) return JSON
    return JsonResponse({'success': False, 'message': 'Invalid request method.'})