from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from django.views.decorators.cache import cache_control
from django.core.paginator import Paginator
from django.utils import timezone
from django.db import transaction
from django.urls import reverse
from django.template.loader import render_to_string
from django.core.mail import EmailMultiAlternatives
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import datetime
import io, os, json
from pathlib import Path
import logging
import stripe

from mainapp.models import *
from adminapp.models import ProductSubQuantity, Offer, Product, get_active_offer_price, StockHistory
from adminapp.stock_utils import convert_quantity_to_base, UNIT_TO_BASE

from .models import Cart, CartItem, Order, OrderItem

logger = logging.getLogger(__name__)
stripe.api_key = getattr(settings, 'STRIPE_SECRET_KEY', '')


# -- Helpers (unchanged) --
def _write_invoice_file_bytes(order_id, pdf_bytes):
    invoices_dir = Path(settings.MEDIA_ROOT) / "invoices"
    invoices_dir.mkdir(parents=True, exist_ok=True)
    filename = f"invoice_{order_id}.pdf"
    filepath = invoices_dir / filename
    with open(filepath, "wb") as f:
        f.write(pdf_bytes)
    return str(filepath), filename


def _generate_invoice_bytes_and_context(order, user, request):
    order_items = list(order.items.select_related('product', 'variant'))
    invoice_context = {
        'order': order,
        'items': order_items,
        'user': user,
        'site_name': getattr(settings, 'SITE_NAME', 'FreshHarvest'),
        'now': timezone.localtime(),
        'logo_url': request.build_absolute_uri(settings.STATIC_URL + 'admin/assets/images/logo.png'),
        'invoice_download_url': None
    }
    html_invoice = render_to_string('invoice_pdf.html', invoice_context)

    pdf_bytes = None
    attachment_filename = None
    try:
        from weasyprint import HTML
        pdf_bytes = HTML(string=html_invoice, base_url=request.build_absolute_uri('/')).write_pdf()
    except Exception:
        pdf_bytes = None

    if pdf_bytes is None:
        try:
            from xhtml2pdf import pisa
            out = io.BytesIO()
            pisa.CreatePDF(io.StringIO(html_invoice), dest=out)
            pdf_bytes = out.getvalue()
        except Exception:
            pdf_bytes = None

    if pdf_bytes:
        filepath, attachment_filename = _write_invoice_file_bytes(order.id, pdf_bytes)
        invoice_context['invoice_download_url'] = request.build_absolute_uri(settings.MEDIA_URL + f"invoices/{attachment_filename}")
    else:
        invoices_dir = Path(settings.MEDIA_ROOT) / "invoices"
        invoices_dir.mkdir(parents=True, exist_ok=True)
        html_file = invoices_dir / f"invoice_{order.id}.html"
        html_file.write_text(html_invoice, encoding="utf-8")
        invoice_context['invoice_download_url'] = request.build_absolute_uri(settings.MEDIA_URL + f"invoices/{html_file.name}")

    return pdf_bytes, html_invoice, invoice_context, attachment_filename


def send_invoice_email_for_order(order, user, request):
    try:
        pdf_bytes, html_invoice, invoice_context, attachment_filename = _generate_invoice_bytes_and_context(order, user, request)
        subject = f"{getattr(settings, 'SITE_NAME', 'FreshHarvest')} - Order Invoice #{getattr(order, 'order_number', order.id)}"
        plain_body = f"Hello {user.name},\n\nThank you for your order. Your invoice is attached.\n\nOrder ID: {getattr(order,'order_number', order.id)}\nTotal: ₹{order.total_amount}\n\nRegards,\n{getattr(settings,'SITE_NAME','FreshHarvest')}"
        from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', None) or getattr(settings, 'EMAIL_HOST_USER', None) or 'no-reply@freshharvest.local'

        email_html = render_to_string('invoice_email.html', invoice_context)

        em = EmailMultiAlternatives(subject=subject, body=plain_body, from_email=from_email, to=[user.email])
        em.attach_alternative(email_html, "text/html")
        if pdf_bytes and attachment_filename:
            em.attach(attachment_filename, pdf_bytes, 'application/pdf')
        em.send(fail_silently=False)
        logger.info("Invoice email sent for order %s to %s", order.id, user.email)
        return True
    except Exception as e:
        logger.exception("Failed to generate/send invoice email for order %s to %s: %s", getattr(order,'id',None), getattr(user,'email',None), str(e))
        return False


def _get_unit_factor(product):
    try:
        uname = (product.unit.name or "").strip().lower()
    except Exception:
        uname = ''
    return UNIT_TO_BASE.get(uname, {'factor': Decimal('1')})['factor']


# -- Views with session check + cache control applied consistently --

@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def userdash(request):
    if not request.session.get('userid'):
        messages.error(request, "You are not logged in")
        return redirect('login')
    userid = request.session.get('userid')
    try:
        user = UserInfo.objects.get(email=userid)
    except Exception:
        messages.error(request, "User not found")
        return redirect('login')

    now = timezone.localtime()
    hour = now.hour
    if 5 <= hour < 12:
        greeting = "Good morning"
    elif 12 <= hour < 17:
        greeting = "Good afternoon"
    elif 17 <= hour < 21:
        greeting = "Good evening"
    else:
        greeting = "Good night"

    try:
        cart = Cart.objects.filter(user=user).first()
        cart_count = CartItem.objects.filter(cart=cart).count() if cart else 0
    except Exception:
        cart_count = 0
    product_count = Product.objects.all().count()
    order_count = Order.objects.filter(user=user).count()

    recent_offers = []
    try:
        now_dt = timezone.now()
        offers_qs = Offer.objects.filter(
            active=True,
            start_datetime__lte=now_dt,
            end_datetime__gte=now_dt
        ).order_by('-start_datetime')[:5]
        for o in offers_qs:
            first_prod = o.items.select_related('product').first()
            img = ""
            try:
                if first_prod and getattr(first_prod.product, 'cover_image', None):
                    img = first_prod.product.cover_image.url
            except Exception:
                img = ""
            recent_offers.append({
                'id': o.id,
                'title': o.title,
                'description': (o.description or "")[:200],
                'end_datetime': o.end_datetime,
                'first_product_id': first_prod.product.id if first_prod else None,
                'image': img
            })
    except Exception:
        recent_offers = []

    context = {
        'name': user.name,
        'userid': userid,
        'profile': user.profile,
        'greeting': greeting,
        'cart_count': cart_count,
        'product_count': product_count,
        'order_count': order_count,
        'recent_offers': recent_offers,
    }
    return render(request, 'userdash.html', context)


@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def userlogout(request):
    if request.session.get('userid'):
        del request.session['userid']
        messages.success(request, 'You are logged out')
        return redirect('login')
    else:
        return redirect('index')


@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def viewcart(request):
    if not request.session.get('userid'):
        messages.error(request, "You are not logged in")
        return redirect('login')
    userid = request.session.get('userid')
    user = UserInfo.objects.get(email=userid)
    ucart = Cart.objects.filter(user=user).first()
    if ucart is None:
        cart = Cart(user=user)
        cart.save()

    items = list(CartItem.objects.filter(cart=Cart.objects.filter(user=user).first()).select_related('product', 'variant'))

    grand_total = Decimal('0.00')
    for i in items:
        try:
            qty = Decimal(str(i.quantity or '0'))
        except Exception:
            qty = Decimal('0')

        if getattr(i, 'price', None) is not None:
            try:
                line_total = Decimal(str(i.price)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            except Exception:
                line_total = Decimal('0.00')
            if qty > 0:
                try:
                    per_unit = (line_total / qty).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                except Exception:
                    per_unit = None
            else:
                per_unit = None
        else:
            variant = getattr(i, 'variant', None)
            try:
                base_price_raw = get_active_offer_price(i.product)[0]
                base_price = Decimal(str(base_price_raw))
            except Exception:
                base_price = Decimal(str(getattr(i.product, 'price', '0') or '0'))

            if variant and getattr(variant, 'price', None) not in (None, ''):
                try:
                    v_price = Decimal(str(variant.price))
                    factor = Decimal(str(getattr(variant, 'factor_to_base', '1') or '1'))
                    per_unit = (v_price / factor).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP) if factor != 0 else base_price.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                except Exception:
                    per_unit = base_price.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            else:
                per_unit = base_price.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

            try:
                line_total = (per_unit * qty).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            except Exception:
                line_total = Decimal('0.00')

        i.display_per_unit = per_unit
        i.display_line_total = line_total
        grand_total += (line_total or Decimal('0.00'))

    grand_total = grand_total.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    context = {
        'name': user.name,
        'userid': userid,
        'profile': user.profile,
        'items': items,
        'total': grand_total
    }
    return render(request, 'viewcart.html', context)


@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def removeitem(request, id):
    if not request.session.get('userid'):
        messages.error(request, "You are not logged in")
        return redirect('login')
    userid = request.session.get('userid')
    user = UserInfo.objects.get(email=userid)
    ucart = Cart.objects.filter(user=user).first()
    product = Product.objects.get(id=id)
    CartItem.objects.filter(cart=ucart, product=product).delete()
    messages.success(request, "Product removed from cart")
    return redirect('viewcart')


# ...existing code...
@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def checkout(request):
    if not request.session.get('userid'):
        messages.error(request, "You are not logged in")
        return redirect('login')

    userid = request.session.get('userid')
    try:
        user = UserInfo.objects.get(email=userid)
    except Exception:
        messages.error(request, "User not found")
        return redirect('login')

    buy_now_item = request.session.pop('buy_now_item', None)
    items_for_checkout = []
    grand_total = Decimal('0.00')

    if buy_now_item:
        try:
            pid = int(buy_now_item.get('product_id'))
            product = Product.objects.get(pk=pid)
        except Exception:
            messages.error(request, "Product not found for Buy Now")
            return redirect('viewcart')

        try:
            qty = Decimal(str(buy_now_item.get('quantity') or '1'))
        except Exception:
            qty = Decimal('1')
        try:
            line_total = Decimal(str(buy_now_item.get('line_total') or '0')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        except Exception:
            line_total = Decimal('0.00')

        variant = None
        if buy_now_item.get('variant_id'):
            try:
                vid = int(buy_now_item.get('variant_id'))
                variant = ProductSubQuantity.objects.filter(pk=vid, product=product).first()
            except Exception:
                variant = None

        if line_total <= 0:
            messages.error(request, "Invalid line total for Buy Now")
            return redirect('product_details', id=product.id)

        items_for_checkout.append({
            'product': product,
            'variant': variant,
            'qty': qty,
            'line_total': line_total,
            'desc': f"{product.title}" + (f" - {variant.name}" if variant and getattr(variant, 'name', None) else "")
        })
        grand_total = line_total
    else:
        try:
            cart = Cart.objects.get(user=user)
        except Cart.DoesNotExist:
            messages.error(request, "Cart not found")
            return redirect('viewcart')

        cart_items = list(CartItem.objects.filter(cart=cart).select_related('product', 'variant'))
        if not cart_items:
            messages.error(request, "Your cart is empty")
            return redirect('viewcart')

        for ci in cart_items:
            p = ci.product
            try:
                qty = Decimal(str(ci.quantity or 0))
            except Exception:
                qty = Decimal('0')

            # skip non-positive quantities
            if qty <= 0:
                continue

            # If CartItem has an explicit stored line price (legacy), use it
            if getattr(ci, 'price', None) is not None:
                try:
                    line_total = Decimal(str(ci.price)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                except Exception:
                    line_total = Decimal('0.00')
                per_unit_price = (line_total / qty).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP) if qty > 0 else line_total
            else:
                # compute per-base unit price either from variant price or active offer / product price
                per_unit_price = Decimal('0.00')
                try:
                    if ci.variant and getattr(ci.variant, 'price', None) not in (None, ''):
                        v_price = Decimal(str(ci.variant.price))
                        factor = Decimal(str(getattr(ci.variant, 'factor_to_base', '1') or '1'))
                        per_unit_price = (v_price / factor).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP) if factor != 0 else Decimal('0.00')
                    else:
                        # use active offer price if present, otherwise product.price
                        try:
                            base_price_raw = get_active_offer_price(ci.product)[0]
                            per_unit_price = Decimal(str(base_price_raw)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                        except Exception:
                            per_unit_price = Decimal(str(getattr(ci.product, 'price', '0') or '0')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                except Exception:
                    per_unit_price = Decimal('0.00')

                try:
                    line_total = (per_unit_price * qty).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                except Exception:
                    line_total = Decimal('0.00')

            # skip zero or negative priced items
            if line_total <= 0:
                continue

            items_for_checkout.append({
                'product': p,
                'variant': ci.variant,
                'qty': qty,
                'line_total': line_total,
                'desc': f"{p.title}" + (f" - {ci.variant.name}" if ci.variant and getattr(ci.variant, 'name', None) else "")
            })
            grand_total += line_total

    grand_total = grand_total.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    if not items_for_checkout:
        messages.error(request, "No payable items for checkout")
        return redirect('viewcart')

    line_items = []
    for it in items_for_checkout:
        unit_amount_cents = int((it['line_total'] * Decimal('100')).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
        line_items.append({
            'price_data': {
                'currency': 'inr',
                'product_data': {'name': it['desc']},
                'unit_amount': unit_amount_cents,
            },
            'quantity': 1,
        })

    try:
        request.session['checkout_total'] = str(grand_total)
    except Exception:
        pass

    try:
        success_path = reverse('payment_success')
    except Exception:
        success_path = '/userapp/payment_success/'
    try:
        cancel_path = reverse('viewcart')
    except Exception:
        cancel_path = '/viewcart/'

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=line_items,
            mode='payment',
            success_url=request.build_absolute_uri(success_path),
            cancel_url=request.build_absolute_uri(cancel_path),
        )
    except Exception as e:
        messages.error(request, f"Payment initialization failed: {str(e)}")
        return redirect('viewcart')

    return redirect(session.url, code=303)
# ...existing code...

@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def payment_success(request):
    try:
        autoredirect = reverse('userorders')
    except Exception:
        autoredirect = '/userapp/userorders/'

    userid = request.session.get('userid')
    if not userid:
        return render(request, 'payment_success.html', {'order': None, 'autoredirect_url': autoredirect})

    try:
        user = UserInfo.objects.get(email=userid)
    except Exception:
        return render(request, 'payment_success.html', {'order': None, 'autoredirect_url': autoredirect})

    cart = Cart.objects.filter(user=user).first()
    if not cart:
        return render(request, 'payment_success.html', {'order': None, 'autoredirect_url': autoredirect})

    cart_items = CartItem.objects.filter(cart=cart).select_related('product', 'variant')
    if not cart_items.exists():
        return render(request, 'payment_success.html', {'order': None, 'autoredirect_url': autoredirect})

    try:
        with transaction.atomic():
            for item in cart_items:
                p = item.product
                try:
                    required = convert_quantity_to_base(item.quantity, p, item.variant)
                except Exception:
                    try:
                        required = Decimal(str(item.quantity or 0))
                    except Exception:
                        required = Decimal('0')
                available = Decimal(str(getattr(p, 'stock', 0) or 0))
                if required > available:
                    messages.error(request, f"Insufficient stock for {getattr(p, 'title', 'product')}. Available: {available}, required: {required}")
                    return redirect('viewcart')

            total_amount = Decimal('0.00')
            per_item_snapshots = []
            for ci in cart_items:
                qty = Decimal(str(ci.quantity or 0))
                if getattr(ci, 'price', None) is not None:
                    line_total = Decimal(str(ci.price)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                    try:
                        if qty > 0:
                            per_base_snapshot = (line_total / qty).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                        else:
                            per_base_snapshot = Decimal('0.00')
                    except Exception:
                        per_base_snapshot = Decimal('0.00')
                else:
                    if ci.variant and getattr(ci.variant, 'price', None) not in (None, ''):
                        v_price = Decimal(str(ci.variant.price))
                        factor = Decimal(str(getattr(ci.variant, 'factor_to_base', '1') or '1'))
                        per_base_snapshot = (v_price / factor) if factor != 0 else Decimal('0.00')
                        line_total = (per_base_snapshot * qty).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                    else:
                        try:
                            base_price = Decimal(str(get_active_offer_price(ci.product)[0]))
                        except Exception:
                            base_price = Decimal('0.00')
                        per_base_snapshot = base_price.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                        line_total = (per_base_snapshot * qty).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

                total_amount += line_total
                per_item_snapshots.append((ci, per_base_snapshot, line_total))

            total_amount = total_amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

            order = Order.objects.create(user=user, total_amount=total_amount)

            for ci, per_base_price, line_total in per_item_snapshots:
                p = ci.product
                variant = ci.variant
                qty = Decimal(str(ci.quantity or 0))

                OrderItem.objects.create(
                    order=order,
                    product=p,
                    quantity=ci.quantity,
                    price=per_base_price,
                    variant=variant
                )

                try:
                    deduct = convert_quantity_to_base(ci.quantity, p, variant)
                except Exception:
                    try:
                        deduct = Decimal(str(ci.quantity or 0))
                    except Exception:
                        deduct = Decimal('0')
                try:
                    current_stock = Decimal(str(p.stock or '0'))
                except Exception:
                    current_stock = Decimal('0')
                p.stock = (current_stock - deduct).quantize(Decimal('0.000'), rounding=ROUND_HALF_UP)
                if hasattr(p, 'last_stock_update'):
                    p.last_stock_update = timezone.now()
                    p.save(update_fields=['stock', 'last_stock_update'])
                else:
                    p.save(update_fields=['stock'])

                try:
                    StockHistory.objects.create(product=p, amount=-deduct, reason=f"order {getattr(order, 'order_number', order.id)}", admin_user=None)
                except Exception:
                    pass

            cart_items.delete()
            try:
                request.session['last_order_id'] = order.id
            except Exception:
                pass

        try:
            sent = send_invoice_email_for_order(order, user, request)
            try:
                if sent:
                    request.session[f'invoice_sent_{order.id}'] = True
                    request.session['last_order_id'] = order.id
            except Exception:
                pass
        except Exception:
            logger.exception("Unexpected error in invoice send flow for order %s", getattr(order,'id',None))
            pass

        return render(request, 'payment_success.html', {'order': order, 'autoredirect_url': autoredirect})
    except Exception as exc:
        messages.error(request, f"Order processing failed: {str(exc)}")
        return redirect('viewcart')


@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def userorders(request):
    if not request.session.get('userid'):
        messages.error(request, "You are not logged in")
        return redirect('login')

    userid = request.session.get('userid')
    user = get_object_or_404(UserInfo, email=userid)

    last_order_id = request.session.get('last_order_id')
    if last_order_id and not request.session.get(f'invoice_sent_{last_order_id}'):
        try:
            order_obj = Order.objects.filter(pk=last_order_id, user=user).first()
            if order_obj:
                ok = send_invoice_email_for_order(order_obj, user, request)
                if ok:
                    request.session[f'invoice_sent_{last_order_id}'] = True
                    messages.success(request, "Invoice emailed to your address.")
        except Exception as e:
            logger.exception("Fallback invoice send failed for order %s: %s", last_order_id, str(e))

    filter_type = request.GET.get('filter', 'all')
    date_str = request.GET.get('date', '').strip()

    orders_qs = Order.objects.filter(user=user)

    target_date = None
    today = timezone.localdate()
    if filter_type == 'today':
        target_date = today
    elif filter_type == 'yesterday':
        target_date = today - datetime.timedelta(days=1)
    elif filter_type == 'date' and date_str:
        try:
            target_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            target_date = None

    if target_date:
        orders_qs = orders_qs.filter(ordered_at__date=target_date)

    orders = orders_qs.order_by('-ordered_at')

    orders_with_items = []
    for o in orders:
        items = list(o.items.select_related('product'))
        subtotal = 0
        for it in items:
            it.total_price = (it.price or 0) * (it.quantity or 0)
            subtotal += it.total_price
        order_total = o.total_amount if (o.total_amount and o.total_amount > 0) else subtotal
        orders_with_items.append({
            'order': o,
            'items': items,
            'order_total': order_total,
        })

    context = {
        'name': user.name,
        'userid': userid,
        'profile': user.profile,
        'orders_with_items': orders_with_items,
        'active_filter': filter_type,
        'filter_date': date_str,
    }
    return render(request, 'userorders.html', context)


@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def userprofile(request):
    if not request.session.get('userid'):
        messages.error(request, "You are not logged in")
        return redirect('login')
    userid = request.session.get('userid')
    user = UserInfo.objects.get(email=userid)
    context = {
        'name': user.name,
        'userid': userid,
        'profile': user.profile,
        'user': user
    }
    return render(request, 'userprofile.html', context)


@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def editprofile(request):
    if not request.session.get('userid'):
        messages.error(request, "You are not logged in")
        return redirect('login')
    userid = request.session.get('userid')
    user = UserInfo.objects.get(email=userid)
    if request.method == 'POST':
        name = request.POST.get('name')
        contactno = request.POST.get('contactno')
        address = request.POST.get('address')
        profile = request.FILES.get('profile')
        user.name = name
        user.contactno = contactno
        user.address = address
        if profile:
            user.profile = profile
        user.save()
        messages.success(request, "Profile updated successfully")
        return redirect('userprofile')
    context = {
        'name': user.name,
        'userid': userid,
        'profile': user.profile,
        'user': user
    }
    return render(request, 'editprofile.html', context)


@require_GET
@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def recent_offers_api(request):
    if not request.session.get('userid'):
        return JsonResponse({'count': 0, 'items': []}, status=403)
    now = timezone.now()
    active_qs = Offer.objects.filter(active=True, start_datetime__lte=now, end_datetime__gte=now).order_by('-start_datetime')
    inactive_qs = Offer.objects.exclude(pk__in=active_qs.values('pk')).order_by('-start_datetime')
    combined = list(active_qs) + list(inactive_qs)
    items = []
    for o in combined[:10]:
        prods = []
        for oi in o.items.select_related('product').all()[:3]:
            p = oi.product
            img = ""
            try:
                img = p.cover_image.url if getattr(p, 'cover_image', None) else ""
            except Exception:
                img = getattr(p.cover_image, 'name', '') or ""
            prods.append({'id': p.id, 'title': p.title, 'image': img})
        items.append({
            'id': o.id,
            'title': o.title,
            'description': (o.description or "")[:250],
            'end_datetime': o.end_datetime.isoformat() if o.end_datetime else None,
            'is_active': o.is_active(),
            'products': prods,
        })
    return JsonResponse({'count': active_qs.count(), 'items': items})


@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def view_user_offers(request):
    if not request.session.get('userid'):
        messages.error(request, "You are not logged in")
        return redirect('login')
    now = timezone.now()
    active_qs = Offer.objects.filter(active=True, start_datetime__lte=now, end_datetime__gte=now).order_by('-start_datetime')
    inactive_qs = Offer.objects.exclude(pk__in=active_qs.values('pk')).order_by('-start_datetime')
    offers_list = list(active_qs) + list(inactive_qs)
    for o in offers_list:
        try:
            is_act = bool(o.is_active())
        except Exception:
            is_act = False
        setattr(o, 'is_active', is_act)
        first_item = o.items.select_related('product').first()
        setattr(o, 'first_product_id', first_item.product.id if first_item else None)
    paginator = Paginator(offers_list, 20)
    page = request.GET.get('page', 1)
    page_obj = paginator.get_page(page)
    return render(request, 'view_user_offers.html', {'offers': page_obj, 'now': now})


@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def userchangepassword(request):
    if not request.session.get('userid'):
        messages.error(request, "You are not logged in")
        return redirect('login')
    userid = request.session.get('userid')

    if request.method == "POST":
        oldpwd = request.POST.get('old_password')
        newpwd = request.POST.get('new_password')
        confirmpwd = request.POST.get('confirm_password')
        try:
            login = LoginInfo.objects.get(username=userid)
            if login.password != oldpwd:
                messages.error(request, "Old Password is Incorrect")
                return redirect('userchangepassword')
            elif newpwd != confirmpwd:
                messages.error(request, "New Password and Confirm Password are not same")
                return redirect('userchangepassword')
            elif login.password == newpwd:
                messages.error(request, "New Password is same as Old Password")
                return redirect('userchangepassword')
            else:
                login.password = newpwd
                login.save()
                messages.success(request, "Your password has been changed successfully")
                return redirect('userprofile')
        except LoginInfo.DoesNotExist:
            messages.error(request, "Something went wrong")
            return redirect('login')

    return render(request, 'userchangepassword.html', {'userid': userid})


@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def send_test_email_view(request):
    if not request.session.get('userid'):
        return HttpResponse("Not authorized", status=403)
    try:
        from django.core.mail import send_mail
        send_mail('FreshHarvest test', 'This is a test email from FreshHarvest', getattr(settings,'DEFAULT_FROM_EMAIL', 'no-reply@freshharvest.local'), [request.GET.get('to') or 'your@email'])
        return HttpResponse("Test email sent (check console or SMTP logs).")
    except Exception as e:
        logger.exception("Test email failed: %s", str(e))
        return HttpResponse(f"Error sending test email: {e}", status=500)


# -- Consolidated addtocart (keeps Buy Now support) --
@require_POST
@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def addtocart(request, id=None, product_id=None):
    pid = product_id or id
    if not pid:
        return redirect('products')

    product = get_object_or_404(Product, pk=pid)

    qty_raw = (request.POST.get('quantity') or '1').strip()
    variant_id = (request.POST.get('variant') or '').strip() or None
    line_total_raw = (request.POST.get('line_total') or '').strip() or None

    buy_now_raw = request.POST.get('buy_now')
    buy_now = False
    if buy_now_raw is not None:
        try:
            buy_now = str(buy_now_raw).lower() in ('1', 'true', 'on')
        except Exception:
            buy_now = False

    try:
        qty = Decimal(str(qty_raw))
    except (InvalidOperation, TypeError):
        qty = Decimal('1')
    if qty <= 0:
        qty = Decimal('1')

    line_total = None
    if line_total_raw:
        try:
            line_total = Decimal(str(line_total_raw)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        except Exception:
            line_total = None

    variant = None
    if variant_id:
        try:
            variant = ProductSubQuantity.objects.filter(pk=int(variant_id), product=product).first()
        except Exception:
            variant = None

    if line_total is None:
        try:
            base_price_raw = get_active_offer_price(product)[0]
            base_price = Decimal(str(base_price_raw))
        except Exception:
            base_price = Decimal(str(getattr(product, 'price', '0') or '0'))
        if variant and getattr(variant, 'price', None) not in (None, ''):
            try:
                v_price = Decimal(str(variant.price))
                factor = Decimal(str(getattr(variant, 'factor_to_base', '1') or '1'))
                per_base = (v_price / factor) if factor != 0 else base_price
            except Exception:
                per_base = base_price
        else:
            per_base = base_price
        try:
            line_total = (per_base * qty).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        except Exception:
            line_total = Decimal('0.00')

    userid = request.session.get('userid')
    if not userid:
        messages.error(request, "You must be logged in to add to cart.")
        return redirect('login')
    try:
        user = UserInfo.objects.get(email=userid)
    except Exception:
        messages.error(request, "User not found.")
        return redirect('login')

    cart, _ = Cart.objects.get_or_create(user=user, defaults={'created_at': timezone.now()})

    try:
        with transaction.atomic():
            ci = CartItem.objects.select_for_update().filter(cart=cart, product=product, variant=variant).first()
            if ci:
                try:
                    existing_qty = Decimal(str(ci.quantity or 0))
                except Exception:
                    existing_qty = Decimal('0')
                try:
                    existing_total = Decimal(str(ci.price or 0))
                except Exception:
                    existing_total = Decimal('0.00')

                new_qty = (existing_qty + qty).quantize(Decimal('0.000'), rounding=ROUND_HALF_UP)
                new_total = (existing_total + (line_total or Decimal('0.00'))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

                ci.quantity = new_qty
                if hasattr(ci, 'price'):
                    ci.price = new_total
                    ci.save(update_fields=['quantity', 'price'])
                else:
                    ci.save(update_fields=['quantity'])
            else:
                create_kwargs = {'cart': cart, 'product': product, 'quantity': qty}
                if variant:
                    create_kwargs['variant'] = variant
                if 'price' in [f.name for f in CartItem._meta.get_fields()]:
                    create_kwargs['price'] = line_total
                CartItem.objects.create(**create_kwargs)
        messages.success(request, "Added to cart")
    except Exception as exc:
        messages.error(request, f"Could not add to cart: {str(exc)}")
        return redirect('product_details', id=product.id)

    if buy_now:
        try:
            request.session['buy_now_item'] = {
                'product_id': str(product.id),
                'variant_id': str(variant.id) if variant else '',
                'quantity': str(qty),
                'line_total': str(line_total),
                'title': product.title,
                'variant_name': getattr(variant, 'name', '') or ''
            }
        except Exception:
            request.session.pop('buy_now_item', None)
        return redirect('checkout')

    return redirect('viewcart')