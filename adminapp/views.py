from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.views.decorators.http import require_http_methods, require_POST, require_GET
from mainapp.models import *
from .models import *
from userapp.models import Order, OrderItem, UserInfo
from decimal import Decimal, ROUND_HALF_UP
from django.views.decorators.cache import cache_control
from django.http import JsonResponse, HttpResponseBadRequest
from django.core import serializers
from django.utils.dateparse import parse_date
from django.utils import timezone
import datetime
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db.models import Sum, F, Q, Count
from django.db.models import FloatField, DecimalField
from django.utils.html import escape
from django.db import transaction
from django.urls import reverse
from adminapp.stock_utils import convert_quantity_to_base
import json
from django.template.loader import render_to_string
from django.core.mail import EmailMultiAlternatives
from django.utils.html import strip_tags
from django.conf import settings

# Create your views here.


@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def admindash(request):
    if not request.session.get('adminid'):
        messages.error(request, "You are not logged in")
        return redirect('adminlogin')
    adminid = request.session.get('adminid')

    # total revenue (exclude cancelled orders) - same logic as total_income
    try:
        totals = OrderItem.objects.exclude(order__status=Order.STATUS_CANCELLED).aggregate(
            total_income=Sum(F('quantity') * F('price'), output_field=DecimalField())
        )
        total_revenue = totals.get('total_income') or Decimal('0.00')
    except Exception:
        total_revenue = Decimal('0.00')

    # recent stock alerts (up to 5) for the dashboard card (clickable to checkstock)
    recent_alerts = []
    try:
        alerts_qs = StockAlert.objects.select_related('product').order_by('-created_at')[:5]
        for a in alerts_qs:
            prod = getattr(a, 'product', None)
            page = get_product_page(prod.id) if prod else 1
            recent_alerts.append({
                'id': a.id,
                'product_id': prod.id if prod else None,
                'product_title': getattr(prod, 'title', '') if prod else '',
                'message': a.message,
                'created_at': a.created_at,
                'page': page,
            })
    except Exception:
        recent_alerts = []

    # greeting based on local server time
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

    # optional small trend samples (safe defaults for sparklines)
    users_trend = [5, 6, 4, 8, 7, 9]
    products_trend = [4, 6, 5, 7, 6, 8]
    orders_trend = [2, 4, 3, 6, 5, 7]
    cats_trend = [1, 1, 2, 1, 2, 1]
    revenue_trend = [1000, 1200, 900, 1500, 1300]
    enq_trend = [1, 2, 1, 3, 2, 2]

    context = {
        'adminid': adminid,
        'user_count': UserInfo.objects.all().count(),
        'product_count': Product.objects.all().count(),
        'order_count': Order.objects.all().count(),
        'category_count': Category.objects.all().count(),
        'total_revenue': "%.2f" % (total_revenue or Decimal('0.00')),
        'enquiry_count': Enquiry.objects.all().count(),
        'recent_alerts': recent_alerts,
        'greeting': greeting,
        'users_trend': json.dumps(users_trend),
        'products_trend': json.dumps(products_trend),
        'orders_trend': json.dumps(orders_trend),
        'cats_trend': json.dumps(cats_trend),
        'revenue_trend': json.dumps(revenue_trend),
        'enq_trend': json.dumps(enq_trend),
    }
    return render(request, 'admindash.html', context)


@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def adminlogout(request):
    if request.session.get('adminid'):
        del request.session['adminid']
        messages.success(request, 'You are logged out')
        return redirect('adminlogin')
    else:
        return redirect('index')


@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def viewenq(request):
    if not request.session.get('adminid'):
        messages.error(request, "You are not logged in")
        return redirect('adminlogin')
    enqs = Enquiry.objects.all()
    adminid = request.session.get('adminid')
    return render(request, 'viewenq.html', {'enqs': enqs})


@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def delenq(request, id):
    if not request.session.get('adminid'):
        messages.error(request, "You are not logged in")
        return redirect('adminlogin')
    enq = get_object_or_404(Enquiry, id=id)
    enq.delete()
    messages.success(request, "Enquiry Deleted Successfully")
    return redirect('viewenq')


@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def adminchangepwd(request):
    if not request.session.get('adminid'):
        messages.error(request, "You are not logged in")
        return redirect('adminlogin')
    adminid = request.session.get('adminid')
    if request.method == "POST":
        oldpwd = request.POST.get('oldpwd')
        newpwd = request.POST.get('newpwd')
        confirmpwd = request.POST.get('confirmpwd')
        try:
            admin = LoginInfo.objects.get(username=adminid)
            if admin.password != oldpwd:
                messages.error(request, "Old Password is Incorrect")
                return redirect('adminchangepwd')
            elif newpwd != confirmpwd:
                messages.error(request, "New Password and Confirm Password are not same")
                return redirect('adminchangepwd')
            elif admin.password == newpwd:
                messages.error(request, "New Password is same as Old Password")
                return redirect('adminchangepwd')
            else:
                admin.password = newpwd
                admin.save()
                messages.success(request, "Your password has been changed successfully")
                return redirect('admindash')
        except LoginInfo.DoesNotExist:
            messages.error(request, "Something went wrong")
            return redirect('adminlogin')
    return render(request, 'changepwd.html', {'adminid': adminid})


@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def addunit(request):
    if not request.session.get('adminid'):
        messages.error(request, "You are not logged in")
        return redirect('adminlogin')
    if request.method == "POST":
        name = request.POST.get('name')
        unit = Unit(name=name)
        unit.save()
        messages.success(request, "Unit Added Successfully")
        return redirect('addunit')
    return render(request, 'addunit.html')


@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def viewunit(request):
    if not request.session.get('adminid'):
        messages.error(request, "You are not logged in")
        return redirect('adminlogin')
    units = Unit.objects.all()
    return render(request, 'viewunit.html', {'units': units})


@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def addcat(request):
    if not request.session.get('adminid'):
        messages.error(request, "You are not logged in")
        return redirect('adminlogin')
    if request.method == "POST":
        name = request.POST.get('name')
        description = request.POST.get('description')
        cat = Category(name=name, description=description)
        cat.save()
        messages.success(request, "Category Added Successfully")
        return redirect('addcat')
    return render(request, 'addcat.html')


@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def viewcat(request):
    if not request.session.get('adminid'):
        messages.error(request, "You are not logged in")
        return redirect('adminlogin')
    cats = Category.objects.all()
    return render(request, 'viewcat.html', {'cats': cats})


@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def addproduct(request):
    if not request.session.get('adminid'):
        messages.error(request, "You are not logged in")
        return redirect('adminlogin')
    units = Unit.objects.all()
    cats = Category.objects.all()
    if request.method == "POST":
        title = escape(request.POST.get('title', ''))
        unitid = request.POST.get('unit')
        catid = request.POST.get('category')
        description = escape(request.POST.get('description', ''))
        try:
            unit = Unit.objects.get(id=unitid)
            cat = Category.objects.get(id=catid)
        except (Unit.DoesNotExist, Category.DoesNotExist, ValueError, TypeError):
            messages.error(request, "Invalid unit or category")
            return redirect('addproduct')
        try:
            original_price = Decimal(request.POST.get('original_price'))
            price = Decimal(request.POST.get('price'))
        except Exception:
            messages.error(request, "Invalid price format")
            return redirect('addproduct')
        published_date = request.POST.get('published_date')
        cover_image = request.FILES.get('cover_image')
        stock = request.POST.get('stock')
        product = Product(
            title=title, category=cat, unit=unit, description=description,
            original_price=original_price, price=price, published_date=published_date,
            cover_image=cover_image, stock=stock
        )
        product.save()
        messages.success(request, "New Product is added successfully")
        return redirect('addproduct')
    return render(request, 'addproduct.html', {'cats': cats, 'units': units})


@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def viewproduct(request):
    if not request.session.get('adminid'):
        messages.error(request, 'You are not Logged in')
        return redirect('adminlogin')
    products = Product.objects.select_related('category', 'unit').all()
    cats = Category.objects.all()
    units = Unit.objects.all()
    return render(request, 'viewproduct.html', {'products': products, 'cats': cats, 'units': units})


@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def adminorders(request):
    if not request.session.get('adminid'):
        messages.error(request, "You are not logged in")
        return redirect('adminlogin')

    adminid = request.session.get('adminid')

    # Filters from UI
    filter_type = request.GET.get('filter', 'all')  # supports today/yesterday/date/all
    date_str = request.GET.get('date', '').strip()
    product_id = request.GET.get('product_id', '').strip() or request.GET.get('product_id', '').strip()
    product_name = request.GET.get('product_name', '').strip()
    category = request.GET.get('category', '').strip()
    start_date_str = request.GET.get('start_date', '').strip()
    end_date_str = request.GET.get('end_date', '').strip()
    range_checked = request.GET.get('range')  # checkbox from template: presence means range
    status_filter = request.GET.get('status', '').strip()

    orders_qs = Order.objects.all()

    # status filter for listing
    if status_filter and status_filter in dict(Order.STATUS_CHOICES):
        orders_qs = orders_qs.filter(status=status_filter)

    # Date filtering logic (support explicit range via checkbox, single date via 'date' or filter shortcuts)
    today = timezone.localdate()
    try:
        if range_checked and start_date_str and end_date_str:
            sd = datetime.datetime.strptime(start_date_str, "%Y-%m-%d").date()
            ed = datetime.datetime.strptime(end_date_str, "%Y-%m-%d").date()
            if sd > ed:
                sd, ed = ed, sd
            orders_qs = orders_qs.filter(ordered_at__date__range=(sd, ed))
        elif date_str:
            try:
                d = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
                orders_qs = orders_qs.filter(ordered_at__date=d)
            except Exception:
                pass
        else:
            # support 'today' / 'yesterday' / default all / or 'filter' query param
            if filter_type == 'today':
                orders_qs = orders_qs.filter(ordered_at__date=today)
            elif filter_type == 'yesterday':
                orders_qs = orders_qs.filter(ordered_at__date=today - datetime.timedelta(days=1))
            # 'all' -> no date filter
    except Exception:
        pass

    # Product / product_name filter
    selected_product = None
    if product_id:
        try:
            pid = int(product_id)
            selected_product = Product.objects.filter(id=pid).first()
            if selected_product:
                orders_qs = orders_qs.filter(items__product__id=pid).distinct()
        except (ValueError, TypeError):
            selected_product = None
    elif product_name:
        # search by product title (matches orders that include products with name)
        orders_qs = orders_qs.filter(items__product__title__icontains=product_name).distinct()

    # Category filter (applies to orders that include items from this category)
    if category and not selected_product:
        orders_qs = orders_qs.filter(items__product__category__name=category).distinct()

    orders_qs = orders_qs.order_by('-ordered_at')

    # Compute summary totals EXCLUDING cancelled orders
    orders_non_cancelled_qs = orders_qs.exclude(status=Order.STATUS_CANCELLED)
    totals_agg = OrderItem.objects.filter(order__in=orders_non_cancelled_qs).aggregate(
        total_items=Count('id'),
        total_revenue=Sum(F('quantity') * F('price'), output_field=DecimalField())
    )
    summary_total_qty = totals_agg.get('total_items') or 0
    summary_total_revenue = totals_agg.get('total_revenue') or Decimal('0.00')

    # If a single product selected, build a focused product report
    product_report = None
    product_user_orders = []
    if selected_product:
        product_items = OrderItem.objects.filter(product_id=selected_product.id, order__in=orders_qs).exclude(order__status=Order.STATUS_CANCELLED).select_related('order', 'order__user', 'product').order_by('-order__ordered_at')
        total_qty = 0
        total_revenue = Decimal('0.00')
        for it in product_items:
            total_qty += 1
            price = it.price or Decimal('0.00')
            qty = it.quantity or 0
            total = (price * qty)
            total_revenue += total
            product_user_orders.append({
                'order_id': it.order.id,
                'order_number': it.order.order_number,
                'user_name': getattr(it.order.user, 'name', ''),
                'user_email': getattr(it.order.user, 'email', ''),
                'user_contact': getattr(it.order.user, 'contactno', ''),
                'quantity': qty,
                'total_price': total,
                'ordered_at': it.order.ordered_at if it.order else None,
            })
        product_report = {
            'product': selected_product,
            'total_qty': total_qty,
            'total_revenue': total_revenue,
        }
        orders_with_items = []
        orders_page = None
    else:
        # Build listing: one group per order (order items inside)
        orders_with_items = []
        for o in orders_qs:
            items = list(o.items.select_related('product', 'product__unit', 'product__category'))
            subtotal = Decimal('0.00')
            for it in items:
                # compute item total for display
                it.total_price = (it.price or Decimal('0.00')) * (it.quantity or 0)
                subtotal += it.total_price
            order_total = o.total_amount if (o.total_amount and o.total_amount > 0) else subtotal
            orders_with_items.append({
                'order': o,
                'items': items,
                'order_total': order_total,
                'user': o.user,
            })

        # pagination
        page = request.GET.get('page', 1)
        paginator = Paginator(orders_with_items, 10)
        try:
            orders_page = paginator.page(page)
        except PageNotAnInteger:
            orders_page = paginator.page(1)
        except EmptyPage:
            orders_page = paginator.page(paginator.num_pages)

    # categories for the select in template
    categories = list(Category.objects.order_by('name').values('id', 'name')[:500])

    context = {
        'adminid': adminid,
        'orders_with_items': orders_with_items,
        'product_report': product_report,
        'product_user_orders': product_user_orders,
        'active_filter': filter_type,
        'filter_date': date_str,
        'active_category': category,
        'start_date': start_date_str,
        'end_date': end_date_str,
        'status_filter': status_filter,
        'summary_total_qty': summary_total_qty,
        'summary_total_revenue': summary_total_revenue,
        'order_status_choices': Order.STATUS_CHOICES,
        'product_id': product_id,
        'product_name': selected_product.title if selected_product else product_name,
        'product_category_name': selected_product.category.name if selected_product and selected_product.category else '',
        'orders_page': orders_page,
        'is_paginated': orders_page is not None and orders_page.has_other_pages() if orders_page else False,
        'page_obj': orders_page,
        'paginator': orders_page.paginator if orders_page else None,
        'orders_count': orders_qs.count(),
        'categories': categories,
    }
    return render(request, 'adminorders.html', context)


@require_POST
@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def admin_update_order_status(request):
    """
    AJAX endpoint to update order status.
    - Enforces forward-only transitions (except cancel allowed until dispatched).
    - Restores stock only once when transitioning to 'cancelled'.
    - Uses transaction + select_for_update to avoid races.
    """
    if not request.session.get('adminid'):
        return JsonResponse({'success': False, 'error': 'Not authorized'}, status=403)

    order_id = request.POST.get('order_id')
    new_status = (request.POST.get('status') or '').strip()

    if not order_id or not new_status:
        return JsonResponse({'success': False, 'error': 'Missing parameters'}, status=400)

    # Validate status choice
    valid_statuses = dict(getattr(Order, 'STATUS_CHOICES', []))
    if new_status not in valid_statuses:
        return JsonResponse({'success': False, 'error': 'Invalid status'}, status=400)

    # helper transition rules
    flow = ['confirmed', 'transit', 'dispatched', 'delivered']

    def is_terminal(s):
        return s in ('delivered', 'cancelled')

    def transition_allowed(current, target):
        if current is None:
            current = ''
        current = str(current)
        target = str(target)
        if target == current:
            return False
        if target == 'cancelled':
            # cancellation allowed until dispatched (not after dispatched/delivered/cancelled)
            return current not in ('dispatched', 'delivered', 'cancelled')
        if is_terminal(current):
            return False
        try:
            cur_idx = flow.index(current) if current in flow else -1
            tgt_idx = flow.index(target) if target in flow else -1
        except ValueError:
            return False
        if cur_idx == -1:
            # if current not in flow, only allow starting flow (confirmed) or allowed forward targets
            return tgt_idx >= 0
        return tgt_idx > cur_idx

    # initial fetch (outside lock) to validate existence and current status
    try:
        order = Order.objects.select_related('user').get(pk=int(order_id))
    except (Order.DoesNotExist, ValueError, TypeError):
        return JsonResponse({'success': False, 'error': 'Order not found'}, status=404)

    old_status = order.status or ''

    if not transition_allowed(old_status, new_status):
        return JsonResponse({'success': False, 'error': 'Transition not allowed', 'status': old_status}, status=400)

    # perform update inside transaction with row lock
    try:
        with transaction.atomic():
            # lock order row to avoid concurrent updates
            locked_order = Order.objects.select_for_update().get(pk=order.id)
            # re-check current status after acquiring lock
            current_locked_status = locked_order.status or ''
            if not transition_allowed(current_locked_status, new_status):
                return JsonResponse({'success': False, 'error': 'Transition no longer allowed', 'status': current_locked_status}, status=400)

            # If cancelling now and wasn't cancelled before, restore stock
            if new_status == 'cancelled' and current_locked_status != 'cancelled':
                # ensure we iterate order items and add back base quantities
                items_qs = OrderItem.objects.filter(order=locked_order).select_related('product', 'variant')
                for it in items_qs:
                    p = getattr(it, 'product', None)
                    if not p:
                        continue
                    variant = getattr(it, 'variant', None) if hasattr(it, 'variant') else None
                    try:
                        # convert quantity to base using existing util (returns Decimal)
                        to_add = convert_quantity_to_base(it.quantity, p, variant)
                        # ensure Decimal
                        to_add = Decimal(str(to_add or 0))
                    except Exception:
                        # fallback: treat quantity as base decimal
                        try:
                            to_add = Decimal(str(it.quantity or 0))
                        except Exception:
                            to_add = Decimal('0')

                    try:
                        cur_stock = Decimal(str(getattr(p, 'stock', '0') or '0'))
                    except Exception:
                        cur_stock = Decimal('0')

                    new_stock = (cur_stock + to_add)
                    # update timestamp field if present
                    now = timezone.now()
                    # assign and save safely (detect available timestamp field)
                    p.stock = new_stock
                    if hasattr(p, 'last_stock_update'):
                        p.last_stock_update = now
                        p.save(update_fields=['stock', 'last_stock_update'])
                    elif hasattr(p, 'updated_at'):
                        p.updated_at = now
                        p.save(update_fields=['stock', 'updated_at'])
                    else:
                        p.save(update_fields=['stock'])

                    # StockHistory (optional)
                    try:
                        StockHistory.objects.create(
                            product=p,
                            amount=to_add,
                            reason=f"Reverted by admin cancel of order {locked_order.order_number or locked_order.id}",
                            admin_user=request.session.get('adminid')
                        )
                    except Exception:
                        # ignore history errors
                        pass

            # finally set new status
            locked_order.status = new_status
            locked_order.save(update_fields=['status'])
            resp_status = locked_order.status
    except Exception as exc:
        return JsonResponse({'success': False, 'error': str(exc)}, status=500)

    return JsonResponse({'success': True, 'status': resp_status, 'order_number': getattr(order, 'order_number', order.id)})


@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def transitorders(request):
    if not request.session.get('adminid'):
        messages.error(request, "You are not logged in")
        return redirect('adminlogin')

    adminid = request.session.get('adminid')

    filter_type = request.GET.get('filter', 'all')
    date_str = request.GET.get('date', '').strip()
    orders_qs = Order.objects.filter(status=Order.STATUS_TRANSIT)

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

    orders_qs = orders_qs.order_by('-ordered_at')

    orders_with_items = []
    for o in orders_qs:
        items = list(o.items.select_related('product'))
        subtotal = Decimal('0.00')
        for it in items:
            it.total_price = (it.price or Decimal('0.00')) * (it.quantity or 0)
            subtotal += it.total_price
        order_total = o.total_amount if (o.total_amount and o.total_amount > 0) else subtotal
        orders_with_items.append({
            'order': o,
            'items': items,
            'order_total': order_total,
            'user': o.user,
        })

    # PAGINATION LOGIC
    page = request.GET.get('page', 1)
    paginator = Paginator(orders_with_items, 10)  # 10 orders per page
    try:
        orders_page = paginator.page(page)
    except PageNotAnInteger:
        orders_page = paginator.page(1)
    except EmptyPage:
        orders_page = paginator.page(paginator.num_pages)

    context = {
        'adminid': adminid,
        'orders_page': orders_page,
        'is_paginated': orders_page.has_other_pages(),
        'page_obj': orders_page,
        'paginator': paginator,
        'active_filter': filter_type,
        'filter_date': date_str,
    }
    return render(request, 'transitorders.html', context)


@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def dispatchedorders(request):
    if not request.session.get('adminid'):
        messages.error(request, "You are not logged in")
        return redirect('adminlogin')

    adminid = request.session.get('adminid')

    filter_type = request.GET.get('filter', 'all')
    date_str = request.GET.get('date', '').strip()
    orders_qs = Order.objects.filter(status=Order.STATUS_DISPATCHED)

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

    orders_qs = orders_qs.order_by('-ordered_at')

    orders_with_items = []
    for o in orders_qs:
        items = list(o.items.select_related('product'))
        subtotal = Decimal('0.00')
        for it in items:
            it.total_price = (it.price or Decimal('0.00')) * (it.quantity or 0)
            subtotal += it.total_price
        order_total = o.total_amount if (o.total_amount and o.total_amount > 0) else subtotal
        orders_with_items.append({
            'order': o,
            'items': items,
            'order_total': order_total,
            'user': o.user,
        })

    # PAGINATION LOGIC
    page = request.GET.get('page', 1)
    paginator = Paginator(orders_with_items, 10)  # 10 orders per page
    try:
        orders_page = paginator.page(page)
    except PageNotAnInteger:
        orders_page = paginator.page(1)
    except EmptyPage:
        orders_page = paginator.page(paginator.num_pages)

    context = {
        'adminid': adminid,
        'orders_page': orders_page,
        'is_paginated': orders_page.has_other_pages(),
        'page_obj': orders_page,
        'paginator': paginator,
        'active_filter': filter_type,
        'filter_date': date_str,
    }
    return render(request, 'dispatchedorders.html', context)


@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def cancelledorders(request):
    if not request.session.get('adminid'):
        messages.error(request, "You are not logged in")
        return redirect('adminlogin')

    adminid = request.session.get('adminid')

    filter_type = request.GET.get('filter', 'all')
    date_str = request.GET.get('date', '').strip()
    orders_qs = Order.objects.filter(status=Order.STATUS_CANCELLED)

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

    orders_qs = orders_qs.order_by('-ordered_at')

    orders_with_items = []
    for o in orders_qs:
        items = list(o.items.select_related('product'))
        subtotal = Decimal('0.00')
        for it in items:
            it.total_price = (it.price or Decimal('0.00')) * (it.quantity or 0)
            subtotal += it.total_price
        order_total = o.total_amount if (o.total_amount and o.total_amount > 0) else subtotal
        orders_with_items.append({
            'order': o,
            'items': items,
            'order_total': order_total,
            'user': o.user,
        })

    # PAGINATION LOGIC
    page = request.GET.get('page', 1)
    paginator = Paginator(orders_with_items, 10)  # 10 orders per page
    try:
        orders_page = paginator.page(page)
    except PageNotAnInteger:
        orders_page = paginator.page(1)
    except EmptyPage:
        orders_page = paginator.page(paginator.num_pages)

    context = {
        'adminid': adminid,
        'orders_page': orders_page,
        'is_paginated': orders_page.has_other_pages(),
        'page_obj': orders_page,
        'paginator': paginator,
        'active_filter': filter_type,
        'filter_date': date_str,
    }
    return render(request, 'cancelledorders.html', context)


@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def deliveredorders(request):
    if not request.session.get('adminid'):
        messages.error(request, "You are not logged in")
        return redirect('adminlogin')

    adminid = request.session.get('adminid')

    filter_type = request.GET.get('filter', 'all')
    date_str = request.GET.get('date', '').strip()
    orders_qs = Order.objects.filter(status=Order.STATUS_DELIVERED)

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

    orders_qs = orders_qs.order_by('-ordered_at')

    orders_with_items = []
    for o in orders_qs:
        items = list(o.items.select_related('product'))
        subtotal = Decimal('0.00')
        for it in items:
            it.total_price = (it.price or Decimal('0.00')) * (it.quantity or 0)
            subtotal += it.total_price
        order_total = o.total_amount if (o.total_amount and o.total_amount > 0) else subtotal
        orders_with_items.append({
            'order': o,
            'items': items,
            'order_total': order_total,
            'user': o.user,
        })

    # PAGINATION LOGIC
    page = request.GET.get('page', 1)
    paginator = Paginator(orders_with_items, 10)  # 10 orders per page
    try:
        orders_page = paginator.page(page)
    except PageNotAnInteger:
        orders_page = paginator.page(1)
    except EmptyPage:
        orders_page = paginator.page(paginator.num_pages)

    context = {
        'adminid': adminid,
        'orders_page': orders_page,
        'is_paginated': orders_page.has_other_pages(),
        'page_obj': orders_page,
        'paginator': paginator,
        'active_filter': filter_type,
        'filter_date': date_str,
    }
    return render(request, 'deliveredorders.html', context)


@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def deletecat(request, id):
    if not request.session.get('adminid'):
        messages.error(request, "You are not logged in")
        return redirect('adminlogin')
    cat = get_object_or_404(Category, id=id)
    cat.delete()
    messages.success(request, "Category deleted successfully")
    return redirect('viewcat')


@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def editcat(request, id):
    if not request.session.get('adminid'):
        messages.error(request, "You are not logged in")
        return redirect('adminlogin')
    cat = get_object_or_404(Category, id=id)
    if request.method == "POST":
        name = request.POST.get('name')
        description = request.POST.get('description')
        cat.name = name
        cat.description = description
        cat.save()
        messages.success(request, "Category updated successfully")
        return redirect('viewcat')
    return render(request, 'editcat.html', {'cat': cat})


@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def deleteunit(request, id):
    if not request.session.get('adminid'):
        messages.error(request, "You are not logged in")
        return redirect('adminlogin')
    unit = get_object_or_404(Unit, id=id)
    unit.delete()
    messages.success(request, "Unit deleted successfully")
    return redirect('viewunit')


@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def editunit(request, id):
    if not request.session.get('adminid'):
        messages.error(request, "You are not logged in")
        return redirect('adminlogin')
    unit = get_object_or_404(Unit, id=id)
    if request.method == "POST":
        name = request.POST.get('name')
        unit.name = name
        unit.save()
        messages.success(request, "Unit updated successfully")
        return redirect('viewunit')
    return render(request, 'editunit.html', {'unit': unit})


@require_GET
@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def income_search(request):
    """
    AJAX autocomplete for admin filters.
    Query params:
      - type: 'product' or 'category'
      - q: search string
    Returns JSON { results: [...] }
    """
    if not request.session.get('adminid'):
        return JsonResponse({'results': []}, status=403)
    q = (request.GET.get('q') or '').strip()
    typ = (request.GET.get('type') or 'product').lower()
    if not q:
        return JsonResponse({'results': []})

    results = []
    try:
        if typ == 'category':
            qs = Category.objects.filter(name__icontains=q).order_by('name')[:30]
            for c in qs:
                results.append({
                    'id': c.id,
                    'name': escape(c.name),
                })
        else:
            qs = Product.objects.select_related('unit', 'category').filter(title__icontains=q).order_by('title')[:40]
            for p in qs:
                results.append({
                    'id': p.id,
                    'title': escape(p.title),
                    'image': p.cover_image.url if getattr(p, 'cover_image', None) else '',
                    'price': str(p.price) if getattr(p, 'price', None) is not None else '',
                    'unit': escape(p.unit.name) if getattr(p, 'unit', None) else '',
                    'category_id': p.category.id if getattr(p, 'category', None) else '',
                    'category_name': escape(p.category.name) if getattr(p, 'category', None) else '',
                })
    except Exception:
        # fail gracefully
        return JsonResponse({'results': []})
    return JsonResponse({'results': results})


@require_GET
@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def total_income(request):
    """
    Admin total income view with safe filters and grouping.
    - Count sold items as integer number of OrderItem rows (Count('id')).
    - Totals exclude cancelled orders from aggregates.
    - Breakdown rows now include human-friendly quantity + unit (e.g. "0.25 kg (250 gm)" or "250 gm").
    """
    if not request.session.get('adminid'):
        messages.error(request, "You are not logged in")
        return redirect('adminlogin')

    params = request.GET
    search_type = (params.get('search_type') or 'product').lower()
    search_id = (params.get('search_id') or '').strip()
    search_name = (params.get('search_name') or '').strip()
    date_filter = (params.get('date_filter') or 'today').lower()
    date_str = (params.get('date') or '').strip()
    start_date_str = (params.get('start_date') or '').strip()
    end_date_str = (params.get('end_date') or '').strip()
    status_filter = (params.get('status') or '').strip()

    # If admin explicitly chose category filter but didn't provide a category/id or name -> show message
    if 'search_type' in params and search_type == 'category' and not search_id and not search_name:
        messages.error(request, "Please select a category or enter a category name to filter.")
        return redirect('total_income')

    # If admin asked for "all", ignore specific product/category search inputs
    if search_type == 'all':
        search_id = ''
        search_name = ''

    # Resolve date range
    today = timezone.localdate()
    start_date = end_date = None
    try:
        if date_filter == 'today':
            start_date = end_date = today
        elif date_filter == 'yesterday':
            start_date = end_date = today - datetime.timedelta(days=1)
        elif date_filter == 'last7':
            start_date = today - datetime.timedelta(days=6); end_date = today
        elif date_filter == 'lastmonth':
            start_date = today - datetime.timedelta(days=30); end_date = today
        elif date_filter == 'date' and date_str:
            start_date = end_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
        elif date_filter == 'range' and start_date_str and end_date_str:
            s = datetime.datetime.strptime(start_date_str, "%Y-%m-%d").date()
            e = datetime.datetime.strptime(end_date_str, "%Y-%m-%d").date()
            start_date, end_date = (s, e) if s <= e else (e, s)
    except Exception:
        start_date = end_date = None

    # Base OrderItem queryset
    items_qs = OrderItem.objects.select_related('product', 'product__category', 'order', 'order__user').all()

    # optional status filter (only apply valid choices) — used to narrow listing, but we will exclude cancelled for aggregates
    if status_filter and status_filter in dict(Order.STATUS_CHOICES):
        items_qs = items_qs.filter(order__status=status_filter)

    if start_date:
        items_qs = items_qs.filter(order__ordered_at__date__gte=start_date)
    if end_date:
        items_qs = items_qs.filter(order__ordered_at__date__lte=end_date)

    # Apply search filters safely
    try:
        if search_id:
            sid = int(search_id)
            if search_type == 'category':
                items_qs = items_qs.filter(product__category__id=sid)
            else:
                items_qs = items_qs.filter(product__id=sid)
        elif search_name:
            if search_type == 'category':
                items_qs = items_qs.filter(product__category__name__icontains=search_name)
            else:
                items_qs = items_qs.filter(product__title__icontains=search_name)
    except (ValueError, TypeError):
        pass

    # Exclude cancelled orders from totals and grouping calculations
    items_for_aggregates = items_qs.exclude(order__status=Order.STATUS_CANCELLED)

    # Overall totals (item count = Count('id'), income = Sum(price * quantity))
    totals = items_for_aggregates.aggregate(
        total_items=Count('id'),
        total_income=Sum(F('quantity') * F('price'), output_field=DecimalField())
    )
    total_items_count = totals.get('total_items') or 0
    total_income = totals.get('total_income') or Decimal('0.00')

    # helper to format quantity integer
    def fmt_qty_int(n):
        try:
            return str(int(n))
        except Exception:
            return str(n)

    # helper to format purchased quantity with unit
    def format_qty_with_unit(qty_dec, unit_name):
        try:
            q = Decimal(str(qty_dec))
        except Exception:
            return f"{qty_dec or ''} {unit_name or ''}".strip()

        # show integer without decimals when whole
        if q == q.quantize(Decimal('1')):
            return f"{int(q)} {unit_name}".strip() if unit_name else str(int(q))

        # for kg units show grams as additional friendly format
        u = (unit_name or "").strip().lower()
        if 'kg' in u:
            grams = (q * Decimal('1000')).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
            grams_str = f"{int(grams)} gm" if grams == grams.quantize(Decimal('1')) else f"{grams} gm"
            return f"{q.normalize()} kg ({grams_str})"
        # otherwise show decimal with up to 3 decimal places
        q_str = f"{q.normalize()}"
        return f"{q_str} {unit_name}".strip() if unit_name else q_str

    # Build groups for accordion
    groups = []
    if search_type == 'category' and not search_id:
        # aggregate by category (count items as Count('id'))
        cat_agg = items_for_aggregates.values('product__category__id', 'product__category__name').annotate(
            qty=Count('id'),
            income=Sum(F('quantity') * F('price'), output_field=DecimalField())
        ).order_by('-qty')
        for c in cat_agg:
            cid = c['product__category__id']
            cname = c['product__category__name']
            breakdown_qs = items_qs.filter(product__category__id=cid).order_by('-order__ordered_at')
            breakdown = []
            for it in breakdown_qs:
                try:
                    price_dec = Decimal(str(it.price)) if it.price is not None else Decimal('0.00')
                except Exception:
                    price_dec = Decimal('0.00')
                try:
                    qty_dec = Decimal(str(it.quantity)) if it.quantity is not None else Decimal('0')
                except Exception:
                    qty_dec = Decimal('0')
                total_dec = (price_dec * qty_dec).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

                unit_name = (it.product.unit.name if getattr(it.product, 'unit', None) else '') or ''
                breakdown.append({
                    'user_name': getattr(it.order.user, 'name', '') if it.order and getattr(it.order, 'user', None) else '',
                    'user_email': getattr(it.order.user, 'email', '') if it.order and getattr(it.order, 'user', None) else '',
                    'user_contact': getattr(it.order.user, 'contactno', '') if it.order and getattr(it.order, 'user', None) else '',
                    'product_title': it.product.title if it.product else '',
                    'product_image': it.product.cover_image.url if (it.product and getattr(it.product, 'cover_image', None)) else '',
                    # show actual purchased qty with unit
                    'qty': format_qty_with_unit(qty_dec, unit_name),
                    'unit': unit_name,
                    'price': float(price_dec),
                    'total': float(total_dec),
                    'ordered_at': it.order.ordered_at if it.order else None,
                })
            groups.append({
                'type': 'category',
                'id': cid,
                'name': cname,
                'qty': fmt_qty_int(c.get('qty') or 0),
                'income': float(c.get('income') or Decimal('0.00')),
                'breakdown': breakdown
            })
    else:
        # aggregate by product (count items as Count('id'))
        prod_agg = items_for_aggregates.values(
            'product__id', 'product__title', 'product__unit__name', 'product__category__name'
        ).annotate(
            qty=Count('id'),
            income=Sum(F('quantity') * F('price'), output_field=DecimalField())
        ).order_by('-qty')

        prod_ids = [p['product__id'] for p in prod_agg if p.get('product__id')]
        prod_images = {}
        if prod_ids:
            qs_prod = Product.objects.filter(id__in=prod_ids).only('id', 'cover_image')
            for pr in qs_prod:
                img_url = ""
                try:
                    if pr.cover_image:
                        img_url = pr.cover_image.url
                except Exception:
                    img_url = getattr(pr.cover_image, "name", "") or ""
                prod_images[pr.id] = img_url

        for p in prod_agg:
            pid = p.get('product__id')
            group_unit = p.get('product__unit__name', '') or ''
            breakdown_qs = items_qs.filter(product__id=pid).order_by('-order__ordered_at')
            breakdown = []
            for it in breakdown_qs:
                try:
                    price_dec = Decimal(str(it.price)) if it.price is not None else Decimal('0.00')
                except Exception:
                    price_dec = Decimal('0.00')
                try:
                    qty_dec = Decimal(str(it.quantity)) if it.quantity is not None else Decimal('0')
                except Exception:
                    qty_dec = Decimal('0')
                total_dec = (price_dec * qty_dec).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

                unit_name = (it.product.unit.name if getattr(it.product, 'unit', None) else '') or group_unit or ''
                breakdown.append({
                    'user_name': getattr(it.order.user, 'name', '') if it.order and getattr(it.order, 'user', None) else '',
                    'user_email': getattr(it.order.user, 'email', '') if it.order and getattr(it.order, 'user', None) else '',
                    'user_contact': getattr(it.order.user, 'contactno', '') if it.order and getattr(it.order, 'user', None) else '',
                    # show actual purchased qty with unit
                    'qty': format_qty_with_unit(qty_dec, unit_name),
                    'unit': unit_name,
                    'price': float(price_dec),
                    'total': float(total_dec),
                    'ordered_at': it.order.ordered_at if it.order else None,
                })
            groups.append({
                'type': 'product',
                'id': pid,
                'title': p.get('product__title', ''),
                'image': prod_images.get(pid, "") or "",
                'unit': group_unit,
                'category': p.get('product__category__name', ''),
                'qty': fmt_qty_int(p.get('qty') or 0),
                'income': float(p.get('income') or Decimal('0.00')),
                'breakdown': breakdown
            })

    categories = list(Category.objects.order_by('name').values('id', 'name')[:500])

    context = {
        'search_type': search_type,
        'search_id': search_id,
        'search_name': search_name,
        'date_filter': date_filter,
        'start_date': params.get('start_date', ''),
        'end_date': params.get('end_date', ''),
        'total_qty': fmt_qty_int(total_items_count),
        'total_income': "%.2f" % total_income,
        'groups': groups,
        'categories': categories,
        'status_choices': Order.STATUS_CHOICES,
        'status_filter': status_filter,
    }
    return render(request, 'totalincome.html', context)


@require_GET
@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def recent_orders_api(request):
    """
    Returns JSON:
      - count: number of orders for today (capped at 99+)
      - items: latest 10 order items (order id, user, product, qty, image, total, ordered_at)
    """
    if not request.session.get('adminid'):
        return JsonResponse({'error': 'not authorized'}, status=403)

    # count orders for today
    today = timezone.localdate()
    orders_today_count = Order.objects.filter(ordered_at__date=today).count()
    count_display = f"{orders_today_count}" if orders_today_count <= 99 else "99+"

    # latest 10 order items (flattened) for preview in modal
    recent_items = OrderItem.objects.select_related('order', 'order__user', 'product').order_by('-order__ordered_at')[:10]
    items = []
    for it in recent_items:
        prod = getattr(it, 'product', None)
        img = ""
        if prod and getattr(prod, 'cover_image', None):
            try:
                img = prod.cover_image.url
            except Exception:
                img = getattr(prod.cover_image, 'name', '') or ""
        items.append({
            'order_id': it.order.id if it.order else None,
            'order_number': getattr(it.order, 'order_number', '') if it.order else '',
            'user_name': getattr(it.order.user, 'name', '') if it.order and getattr(it.order, 'user', None) else '',
            'product_title': getattr(prod, 'title', '') if prod else '',
            'product_image': img,
            'quantity': it.quantity,
            'price': float(it.price or 0.0),
            'total': float((it.price or 0) * (it.quantity or 0)),
            'ordered_at': it.order.ordered_at.isoformat() if it.order and it.order.ordered_at else '',
        })

    return JsonResponse({'count': count_display, 'items': items})


@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def recentorders(request):
    """
    Render recentorders page.
    Filters: filter param: today|yesterday|last7|lastmonth|all (default today)
    Pagination: 10 order-items per page (shows most recent first)
    """
    if not request.session.get('adminid'):
        messages.error(request, "You are not logged in")
        return redirect('adminlogin')

    adminid = request.session.get('adminid')
    filter_type = request.GET.get('filter', 'today')
    page = request.GET.get('page', 1)

    today = timezone.localdate()
    items_qs = OrderItem.objects.select_related('order', 'order__user', 'product').all()

    # apply date filter
    try:
        if filter_type == 'today':
            items_qs = items_qs.filter(order__ordered_at__date=today)
        elif filter_type == 'yesterday':
            items_qs = items_qs.filter(order__ordered_at__date=today - datetime.timedelta(days=1))
        elif filter_type == 'last7':
            start = today - datetime.timedelta(days=6)
            items_qs = items_qs.filter(order__ordered_at__date__gte=start, order__ordered_at__date__lte=today)
        elif filter_type == 'lastmonth':
            start = today - datetime.timedelta(days=30)
            items_qs = items_qs.filter(order__ordered_at__date__gte=start, order__ordered_at__date__lte=today)
        # 'all' returns everything
    except Exception:
        pass

    items_qs = items_qs.order_by('-order__ordered_at')

    # pagination: 10 items per page
    paginator = Paginator(items_qs, 10)
    try:
        items_page = paginator.page(page)
    except PageNotAnInteger:
        items_page = paginator.page(1)
    except EmptyPage:
        items_page = paginator.page(paginator.num_pages)

    # prepare simple rows for template
    rows = []
    for it in items_page:
        prod = getattr(it, 'product', None)
        img = ""
        if prod and getattr(prod, 'cover_image', None):
            try:
                img = prod.cover_image.url
            except Exception:
                img = getattr(prod.cover_image, 'name', '') or ""
        rows.append({
            'order_id': it.order.id if it.order else None,
            'order_number': getattr(it.order, 'order_number', '') if it.order else '',
            'user_name': getattr(it.order.user, 'name', '') if it.order and getattr(it.order, 'user', None) else '',
            'product_title': getattr(prod, 'title', '') if prod else '',
            'product_image': img,
            'quantity': it.quantity,
            'price': it.price,
            'total': (it.price or Decimal('0.00')) * (it.quantity or 0),
            'ordered_at': it.order.ordered_at if it.order else None,
        })

    context = {
        'adminid': adminid,
        'items_page': items_page,
        'rows': rows,
        'filter_type': filter_type,
        'paginator': paginator,
        'page_obj': items_page,
        'is_paginated': items_page.has_other_pages(),
    }
    return render(request, 'recentorders.html', context)


@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def addoffer(request):
    """
    Admin add offer. Accepts start_date, start_time, end_date, end_time (times optional).
    product_id[] and offer_price[] arrays appended from JS.
    """
    if not request.session.get('adminid'):
        messages.error(request, "You are not logged in")
        return redirect('adminlogin')

    if request.method == 'POST':
        title = request.POST.get('title', '').strip()
        description = request.POST.get('description', '').strip()

        sd = request.POST.get('start_date', '').strip()
        st = request.POST.get('start_time', '').strip()
        ed = request.POST.get('end_date', '').strip()
        et = request.POST.get('end_time', '').strip()

        product_ids = request.POST.getlist('product_id[]')
        offer_prices = request.POST.getlist('offer_price[]')

        if not title or not sd or not ed:
            messages.error(request, "Please provide title, start and end date.")
            return redirect('addoffer')

        # parse datetimes
        try:
            if st:
                start_dt = datetime.datetime.strptime(f"{sd} {st}", "%Y-%m-%d %H:%M")
            else:
                start_dt = datetime.datetime.strptime(sd, "%Y-%m-%d")
            if et:
                end_dt = datetime.datetime.strptime(f"{ed} {et}", "%Y-%m-%d %H:%M")
            else:
                end_dt = datetime.datetime.strptime(ed, "%Y-%m-%d") + datetime.timedelta(hours=23, minutes=59, seconds=59)
            if timezone.is_naive(start_dt):
                start_dt = timezone.make_aware(start_dt, timezone.get_current_timezone())
            if timezone.is_naive(end_dt):
                end_dt = timezone.make_aware(end_dt, timezone.get_current_timezone())
        except Exception:
            messages.error(request, "Invalid date/time format.")
            return redirect('addoffer')

        if end_dt < start_dt:
            messages.error(request, "End must be same or after start.")
            return redirect('addoffer')

        # create offer and items atomically with verbose error reporting
        import traceback
        try:
            with transaction.atomic():
                offer = Offer.objects.create(title=title, description=description, start_datetime=start_dt, end_datetime=end_dt, active=True)
                added = 0
                for idx, pid in enumerate(product_ids):
                    try:
                        p = Product.objects.get(id=int(pid))
                    except Product.DoesNotExist:
                        continue
                    price_str = offer_prices[idx] if idx < len(offer_prices) else ''
                    try:
                        op = Decimal(price_str) if price_str else p.price
                    except Exception:
                        op = p.price
                    OfferItem.objects.create(offer=offer, product=p, offer_price=op)
                    added += 1
        except Exception as e:
            tb = traceback.format_exc()
            # log to console for debugging
            print("Failed to create offer:", str(e))
            print(tb)
            # show message to admin with short error, instruct to check server console
            messages.error(request, f"Failed to create offer: {str(e)} — see server console for traceback.")
            return redirect('addoffer')

        messages.success(request, f"Offer '{offer.title}' created with {added} products.")
        return redirect('viewoffers')

    # GET
    return render(request, 'addoffer.html', {'adminid': request.session.get('adminid')})


@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def viewoffers(request):
    if not request.session.get('adminid'):
        messages.error(request, "You are not logged in")
        return redirect('adminlogin')

    offers = Offer.objects.prefetch_related('items__product').order_by('-start_datetime')
    rows = []
    now = timezone.now()
    for o in offers:
        rows.append({
            'offer': o,
            'items': list(o.items.select_related('product').all()),
            'is_active_now': o.is_active(),
            'now': now
        })
    return render(request, 'viewoffers.html', {'offers': rows, 'adminid': request.session.get('adminid'), 'now': now})


@require_POST
@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def toggle_offer_item(request, pk):
    if not request.session.get('adminid'):
        return JsonResponse({'error': 'not authorized'}, status=403)
    try:
        oi = OfferItem.objects.get(pk=pk)
    except OfferItem.DoesNotExist:
        return JsonResponse({'error': 'not found'}, status=404)
    action = request.POST.get('action', 'toggle')
    if action == 'unlist':
        oi.unlisted = True
    elif action == 'relist':
        oi.unlisted = False
    else:
        oi.unlisted = not oi.unlisted
    oi.save(update_fields=['unlisted'])
    return JsonResponse({'success': True, 'unlisted': oi.unlisted})


@require_POST
@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def end_offer(request, offer_id):
    if not request.session.get('adminid'):
        messages.error(request, "You are not logged in")
        return redirect('adminlogin')
    try:
        o = Offer.objects.get(pk=offer_id)
    except Offer.DoesNotExist:
        messages.error(request, "Offer not found.")
        return redirect('viewoffers')
    o.active = False
    # set end_datetime to now for clarity
    now = timezone.now()
    o.end_datetime = now
    o.save(update_fields=['active', 'end_datetime'])
    # mark all items unlisted
    o.items.update(unlisted=True)
    messages.success(request, f"Offer '{o.title}' ended.")
    return redirect('viewoffers')


@require_POST
@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def edit_offer(request, offer_id):
    if not request.session.get('adminid'):
        messages.error(request, "You are not logged in")
        return redirect('viewoffers')
    try:
        o = Offer.objects.get(pk=offer_id)
    except Offer.DoesNotExist:
        messages.error(request, "Offer not found")
        return redirect('viewoffers')

    sd = request.POST.get('start_date', '').strip()
    st = request.POST.get('start_time', '').strip()
    ed = request.POST.get('end_date', '').strip()
    et = request.POST.get('end_time', '').strip()

    try:
        if sd and st:
            start_dt = datetime.datetime.strptime(f"{sd} {st}", "%Y-%m-%d %H:%M")
        elif sd:
            start_dt = datetime.datetime.strptime(sd, "%Y-%m-%d")
        else:
            start_dt = o.start_datetime
        if ed and et:
            end_dt = datetime.datetime.strptime(f"{ed} {et}", "%Y-%m-%d %H:%M")
        elif ed:
            end_dt = datetime.datetime.strptime(ed, "%Y-%m-%d") + datetime.timedelta(hours=23, minutes=59, seconds=59)
        else:
            end_dt = o.end_datetime

        if timezone.is_naive(start_dt):
            start_dt = timezone.make_aware(start_dt, timezone.get_current_timezone())
        if timezone.is_naive(end_dt):
            end_dt = timezone.make_aware(end_dt, timezone.get_current_timezone())
    except Exception:
        messages.error(request, "Invalid date/time.")
        return redirect('viewoffers')

    if end_dt < start_dt:
        messages.error(request, "End must be same or after start.")
        return redirect('viewoffers')

    # update offer
    o.start_datetime = start_dt
    o.end_datetime = end_dt
    # if admin extends beyond now and had manually disabled earlier, keep active True if end in future
    if o.end_datetime >= timezone.now():
        o.active = True
    o.save(update_fields=['start_datetime', 'end_datetime', 'active'])

    # Update item prices if passed
    product_ids = request.POST.getlist('product_id[]')
    offer_prices = request.POST.getlist('offer_price[]')
    for idx, pid in enumerate(product_ids):
        try:
            oi = OfferItem.objects.get(offer=o, product_id=int(pid))
            price_str = offer_prices[idx] if idx < len(offer_prices) else ''
            try:
                new_price = Decimal(price_str) if price_str else oi.offer_price
            except Exception:
                new_price = oi.offer_price
            if new_price != oi.offer_price:
                oi.offer_price = new_price
                oi.save(update_fields=['offer_price'])
        except OfferItem.DoesNotExist:
            continue

    messages.success(request, "Offer updated successfully.")
    return redirect('viewoffers')


@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def editproduct(request, id):
    """
    Handle POST from the modal form. Updates product fields and optional cover image,
    then redirects back to viewproduct.
    """
    if not request.session.get('adminid'):
        messages.error(request, "You are not logged in")
        return redirect('adminlogin')

    product = get_object_or_404(Product, id=id)
    if request.method != 'POST':
        return redirect('viewproduct')

    title = escape(request.POST.get('title', '').strip())
    description = escape(request.POST.get('description', '').strip())
    published_date = request.POST.get('published_date', '').strip()
    category_id = request.POST.get('category') or None
    unit_id = request.POST.get('unit') or None
    stock_raw = request.POST.get('stock')
    max_stock_raw = request.POST.get('max_stock')
    subqty_flag = request.POST.get('subquantity_enabled') == 'on'
    try:
        original_price = Decimal(request.POST.get('original_price')) if request.POST.get('original_price') else None
    except Exception:
        original_price = None
    try:
        price = Decimal(request.POST.get('price')) if request.POST.get('price') else None
    except Exception:
        price = None

    if title:
        product.title = title
    product.description = description

    if published_date:
        try:
            product.published_date = published_date
        except Exception:
            pass

    if category_id:
        try:
            product.category = Category.objects.get(pk=int(category_id))
        except Exception:
            pass

    if unit_id:
        try:
            product.unit = Unit.objects.get(pk=int(unit_id))
        except Exception:
            pass

    if stock_raw is not None and stock_raw != '':
        try:
            product.stock = Decimal(stock_raw)
        except Exception:
            pass

    if max_stock_raw is not None and max_stock_raw != '':
        try:
            product.max_stock = Decimal(max_stock_raw)
        except Exception:
            pass

    product.subquantity_enabled = bool(subqty_flag)

    if original_price is not None:
        product.original_price = original_price
    if price is not None:
        product.price = price

    # Replace cover image if new file uploaded
    if 'cover_image' in request.FILES:
        try:
            product.cover_image = request.FILES['cover_image']
        except Exception:
            pass

    product.save()

    # --- Process subquantities arrays (from edit modal) ---
    # Expect arrays: sub_id[], sub_name[], sub_factor[], sub_price[]
    sub_ids = request.POST.getlist('sub_id[]')
    sub_names = request.POST.getlist('sub_name[]')
    sub_factors = request.POST.getlist('sub_factor[]')
    sub_prices = request.POST.getlist('sub_price[]')

    existing = {str(sq.id): sq for sq in product.subquantities.all()}

    processed_ids = set()
    for idx, name in enumerate(sub_names):
        name = (name or '').strip()
        if not name:
            continue
        sid = sub_ids[idx] if idx < len(sub_ids) else ''
        factor = sub_factors[idx] if idx < len(sub_factors) else ''
        price_val = sub_prices[idx] if idx < len(sub_prices) else ''
        # normalize numeric
        try:
            factor_d = Decimal(factor) if factor else Decimal('0.001')
        except Exception:
            factor_d = Decimal('0.001')
        try:
            price_d = Decimal(price_val) if price_val else None
        except Exception:
            price_d = None

        if sid and sid in existing:
            # update
            sq = existing[sid]
            sq.name = name
            sq.factor_to_base = factor_d
            sq.price = price_d
            sq.save(update_fields=['name', 'factor_to_base', 'price'])
            processed_ids.add(sid)
        else:
            # create new
            ProductSubQuantity.objects.create(product=product, name=name, factor_to_base=factor_d, price=price_d)

    # delete any existing subquantities not present in posted list
    for exid, exobj in existing.items():
        if exid not in processed_ids:
            exobj.delete()

    messages.success(request, "Product updated successfully")
    return redirect('viewproduct')


@require_GET
@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def product_subquantities_api(request, product_id):
    if not request.session.get('adminid'):
        return JsonResponse({'results': []}, status=403)
    try:
        p = Product.objects.get(pk=product_id)
    except Product.DoesNotExist:
        return JsonResponse({'results': []})
    out = []
    for sq in p.subquantities.all():
        out.append({
            'id': sq.id,
            'name': sq.name,
            'factor_to_base': str(sq.factor_to_base),
            'price': str(sq.price) if sq.price is not None else None,
        })
    return JsonResponse({'results': out})


@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def deleteproduct(request, id):
    """
    Delete product (POST) and remove stored cover image file if present.
    """
    if not request.session.get('adminid'):
        messages.error(request, "You are not logged in")
        return redirect('adminlogin')
    if request.method != 'POST':
        return redirect('viewproduct')

    product = get_object_or_404(Product, id=id)
    try:
        if getattr(product, 'cover_image', None):
            product.cover_image.delete(save=False)
    except Exception:
        pass
    product.delete()
    messages.success(request, "Product deleted successfully")
    return redirect('viewproduct')


UNIT_TO_BASE = {
    'kg': {'base': 'kg', 'factor': Decimal('1')},
    'pcs': {'base': 'pcs', 'factor': Decimal('1')},
    'dozen': {'base': 'pcs', 'factor': Decimal('12')},
    'ltr': {'base': 'ltr', 'factor': Decimal('1')},
    '250gm': {'base': 'kg', 'factor': Decimal('0.25')},
    '500gm': {'base': 'kg', 'factor': Decimal('0.5')},
    '100gm': {'base': 'kg', 'factor': Decimal('0.1')},
    # add more mappings as needed
}


def _unit_factor_for_product(product):
    """
    Return tuple (base_unit_name, factor) where factor multiplies product.unit quantity to compare with product.stock.
    Example: if product.unit.name == '250gm' and product.stock stored in kg base, then factor = 0.25.
    """
    try:
        uname = (product.unit.name or "").strip().lower()
    except Exception:
        uname = ''
    info = UNIT_TO_BASE.get(uname)
    if info:
        return info['base'], Decimal(info['factor'])
    # default fallback: assume same base and factor 1
    return uname or 'unit', Decimal('1')


@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def checkstock(request):
    """
    Admin checkstock page:
      - shows paginated products (30 per page)
      - search by product title or category (filter dropdown)
      - computes percentage = stock / max_stock * 100
      - computes color: >=60 green, >=40 yellow, <40 red
      - calculates low_stock_count (percentage <10 or out of stock) for admin badge
    """
    if not request.session.get('adminid'):
        messages.error(request, "You are not logged in")
        return redirect('adminlogin')

    q = (request.GET.get('q') or '').strip()
    filter_type = (request.GET.get('filter_type') or 'product').lower()  # 'product' or 'category'
    page = int(request.GET.get('page', 1) or 1)

    products_qs = Product.objects.select_related('category', 'unit').order_by('title')

    if q:
        if filter_type == 'category':
            products_qs = products_qs.filter(category__name__icontains=q)
        else:
            products_qs = products_qs.filter(title__icontains=q)

    paginator = Paginator(products_qs, 30)
    try:
        products_page = paginator.page(page)
    except:
        products_page = paginator.page(1)

    items = []
    low_stock_count = 0
    for p in products_page:
        stock = (p.stock or Decimal('0'))
        max_stock = (p.max_stock or Decimal('0'))
        if max_stock > 0:
            pct = (stock / max_stock * Decimal('100')).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)
        else:
            pct = Decimal('100.0') if stock > 0 else Decimal('0.0')
        pct_val = float(pct)
        if stock == 0:
            color = 'bg-danger'
            label = 'Out of Stock'
        else:
            if pct_val >= 60:
                color = 'bg-success'
            elif pct_val >= 40:
                color = 'bg-warning'
            else:
                color = 'bg-danger'
            label = f"{pct}%"
        if (stock == 0) or (max_stock > 0 and pct_val < 10):
            low_stock_count += 1
            # create alert entries (deduped inside function)
            if stock == 0:
                create_stock_alert_if_needed(p, StockAlert.ALERT_OUT, f"{p.title} is out of stock")
            else:
                create_stock_alert_if_needed(p, StockAlert.ALERT_LOW, f"{p.title} low stock: {pct}%")

        items.append({
            'product': p,
            'stock': stock,
            'max_stock': max_stock,
            'pct': pct,
            'color': color,
            'label': label,
            'last_stock_update': p.last_stock_update,
        })

    context = {
        'items': items,
        'products_page': products_page,
        'paginator': paginator,
        'is_paginated': products_page.has_other_pages(),
        'page_obj': products_page,
        'filter_type': filter_type,
        'q': q,
        'low_stock_count': low_stock_count,
    }
    return render(request, 'checkstock.html', context)


@require_POST
@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def add_stock(request, id):
    """
    POST endpoint from 'Add Stock' modal. Form fields:
      - amount (decimal)
      - max_stock (optional, decimal)
      - reason (optional)
    """
    if not request.session.get('adminid'):
        messages.error(request, "You are not logged in")
        return redirect('adminlogin')

    product = get_object_or_404(Product, id=id)
    try:
        amount = Decimal(request.POST.get('amount') or '0').quantize(Decimal('0.001'), rounding=ROUND_HALF_UP)
    except Exception:
        messages.error(request, "Invalid amount")
        return redirect('checkstock')

    max_stock_val = request.POST.get('max_stock')
    reason = request.POST.get('reason', 'admin add')
    adminid = request.session.get('adminid')

    if amount == 0:
        messages.error(request, "Amount must be non-zero")
        return redirect('checkstock')

    # update product stock and optional max_stock, record history
    product.stock = (product.stock or Decimal('0')) + amount
    if max_stock_val:
        try:
            product.max_stock = Decimal(max_stock_val)
        except Exception:
            pass
    product.last_stock_update = timezone.now()
    product.save(update_fields=['stock', 'max_stock', 'last_stock_update'])

    StockHistory.objects.create(
        product=product,
        amount=amount,
        reason=reason,
        admin_user=adminid
    )
    messages.success(request, f"Added {amount} to {product.title}")
    return redirect('checkstock')


@require_GET
@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def low_stock_count_api(request):
    if not request.session.get('adminid'):

        return JsonResponse({'count': 0})
    cnt = 0
    qs = Product.objects.all()
    for p in qs:
        stock = (p.stock or Decimal('0'))
        max_stock = (p.max_stock or Decimal('0'))
        if stock == 0:
            cnt += 1
        elif max_stock > 0:
            pct = (stock / max_stock * Decimal('100'))
            if pct < 10:
                cnt += 1
    return JsonResponse({'count': cnt})


def create_stock_alert_if_needed(product, alert_type, message, dedupe_hours=24):
    """
    Create a StockAlert for product if same type not created within dedupe_hours.
    """
    cutoff = timezone.now() - datetime.timedelta(hours=dedupe_hours)
    recent_same = StockAlert.objects.filter(product=product, alert_type=alert_type, created_at__gte=cutoff)
    if recent_same.exists():
        return None
    return StockAlert.objects.create(product=product, alert_type=alert_type, message=message)


# helper: compute page number for a product in the ordered product list
def get_product_page(product_id, per_page=30):
    try:
        ids = list(Product.objects.order_by('title').values_list('id', flat=True))
        idx = ids.index(product_id)
        return (idx // per_page) + 1
    except Exception:
        return 1


@require_GET
@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def recent_alerts_api(request):
    if not request.session.get('adminid'):
        return JsonResponse({'count': 0, 'items': []})
    items = []
    qs = StockAlert.objects.select_related('product').all()[:10]
    for a in qs:
        items.append({
            'id': a.id,
            'product_id': a.product.id,
            'product_title': a.product.title,
            'type': a.alert_type,
            'message': a.message,
            'created_at': a.created_at.isoformat(),
            # compute page so client can link directly
            'page': get_product_page(a.product.id, per_page=30),
        })
    count = StockAlert.objects.filter(viewed=False).count()
    return JsonResponse({'count': count, 'items': items})


@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def viewalerts(request):
    if not request.session.get('adminid'):
        messages.error(request, "You are not logged in")
        return redirect('adminlogin')
    # fetch alerts as objects and attach page number to each instance
    alerts_qs = StockAlert.objects.select_related('product').order_by('-created_at').all()
    alerts = []
    for a in alerts_qs:
        try:
            a.page = get_product_page(a.product.id, per_page=30)
        except Exception:
            a.page = 1
        alerts.append(a)
    return render(request, 'viewalerts.html', {'alerts': alerts})


@require_http_methods(['POST'])
@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def add_product_subunits(request, product_id):
    """
    POST endpoint to create/update/delete ProductSubQuantity rows for a product.
    Expected POST arrays: sub_id[], sub_name[], sub_factor[], sub_price[]
    """
    if not request.session.get('adminid'):
        messages.error(request, "Not authorized")
        return redirect('viewproduct')
    product = get_object_or_404(Product, pk=product_id)

    sub_ids = request.POST.getlist('sub_id[]')
    sub_names = request.POST.getlist('sub_name[]')
    sub_factors = request.POST.getlist('sub_factor[]')
    sub_prices = request.POST.getlist('sub_price[]')

    existing = {str(sq.id): sq for sq in product.subquantities.all()}
    processed = set()
    for idx, name in enumerate(sub_names):
        name = (name or '').strip()
        if not name:
            continue
        sid = sub_ids[idx] if idx < len(sub_ids) else ''
        factor_raw = sub_factors[idx] if idx < len(sub_factors) else ''
        price_raw = sub_prices[idx] if idx < len(sub_prices) else ''
        try:
            factor = Decimal(factor_raw) if factor_raw else Decimal('0.001')
        except Exception:
            factor = Decimal('0.001')
        try:
            price = Decimal(price_raw) if price_raw else None
        except Exception:
            price = None

        if sid and sid in existing:
            sq = existing[sid]
            sq.name = name
            sq.factor_to_base = factor
            sq.price = price
            sq.save(update_fields=['name', 'factor_to_base', 'price'])
            processed.add(sid)
        else:
            ProductSubQuantity.objects.create(product=product, name=name, factor_to_base=factor, price=price)

    # delete ones omitted (only if sub_id list was provided)
    if sub_ids:
        for exid, exobj in existing.items():
            if exid not in processed:
                exobj.delete()

    messages.success(request, "Product subunits updated.")
    return redirect('viewproduct')


@require_GET
@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def unit_subunits_api(request, unit_id):
    if not request.session.get('adminid'):
        return JsonResponse({'results': []}, status=403)
    try:
        u = Unit.objects.get(pk=unit_id)
    except Unit.DoesNotExist:
        return JsonResponse({'results': []})
    out = []
    for s in u.subunits.all():
        out.append({
            'id': s.id,
            'name': s.name,
            'factor_to_base': str(s.factor_to_base),
            'price': str(s.price) if s.price is not None else None,
        })
    return JsonResponse({'results': out})


@require_http_methods(['POST'])
@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def add_unit_subunits(request, unit_id):
    if not request.session.get('adminid'):
        messages.error(request, "Not authorized")
        return redirect('viewunit')
    unit = get_object_or_404(Unit, pk=unit_id)

    names = request.POST.getlist('name[]')
    factors = request.POST.getlist('factor[]')
    prices = request.POST.getlist('price[]')
    ids = request.POST.getlist('id[]')

    # Build maps for existing rows: by id and by normalized name (case-insensitive)
    existing_by_id = {str(s.id): s for s in unit.subunits.all()}
    existing_by_name = {(s.name or '').strip().lower(): s for s in unit.subunits.all()}

    processed = set()
    for idx, nm in enumerate(names):
        name = (nm or '').strip()
        if not name:
            continue
        sid = ids[idx] if idx < len(ids) else ''
        factor_raw = factors[idx] if idx < len(factors) else ''
        price_raw = prices[idx] if idx < len(prices) else ''
        try:
            factor = Decimal(factor_raw) if factor_raw else Decimal('0.001')
        except Exception:
            factor = Decimal('0.001')
        try:
            price = Decimal(price_raw) if price_raw else None
        except Exception:
            price = None

        # 1) If id provided and exists -> update
        if sid and sid in existing_by_id:
            su = existing_by_id[sid]
            su.name = name
            su.factor_to_base = factor
            su.price = price
            su.save(update_fields=['name', 'factor_to_base', 'price'])
            processed.add(sid)
            # update name map in case name changed
            existing_by_name.pop((su.name or '').strip().lower(), None)
            existing_by_name[(name or '').strip().lower()] = su
            continue

        # 2) Try match by normalized name to avoid creating duplicate of same name
        norm = name.lower()
        if norm in existing_by_name:
            su = existing_by_name[norm]
            su.name = name
            su.factor_to_base = factor
            su.price = price
            su.save(update_fields=['name', 'factor_to_base', 'price'])
            processed.add(str(su.id))
            continue

        # 3) No existing match -> create new
        try:
            UnitSubUnit.objects.create(unit=unit, name=name, factor_to_base=factor, price=price)
        except Exception:
            # on race/constraint errors try to update existing fallback
            existing = UnitSubUnit.objects.filter(unit=unit, name__iexact=name).first()
            if existing:
                existing.factor_to_base = factor
                existing.price = price
                existing.save(update_fields=['factor_to_base', 'price'])

    # If id[] were provided, remove those existing rows that were not submitted (optional)
    if ids:
        for exid, exobj in existing_by_id.items():
            if exid not in processed:
                exobj.delete()

    messages.success(request, "Subunits updated")
    return redirect('viewunit')


def view_subscribed(request):
    if not request.session.get('adminid'):
        messages.error(request, "You are not logged in")
        return redirect('adminlogin')
    qs = Subscriber.objects.order_by('-subscribed_at').all()
    # pagination: 10 per page
    page = request.GET.get('page', 1)
    from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
    paginator = Paginator(qs, 10)
    try:
        page_obj = paginator.page(page)
    except (PageNotAnInteger, EmptyPage):
        page_obj = paginator.page(1)

    return render(request, 'view_subscribed.html', {
        'page_obj': page_obj,
        'paginator': paginator,
        'is_paginated': paginator.num_pages > 1,
        'adminid': request.session.get('adminid')
    })


@require_POST
@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def send_note(request):
    if not request.session.get('adminid'):
        return JsonResponse({'success': False, 'error': 'unauthorized'}, status=403)

    to_addr = (request.POST.get('to') or '').strip()
    subject = (request.POST.get('subject') or '').strip()
    body = (request.POST.get('body') or '').strip()
    template_flag = (request.POST.get('template') or '').strip()

    if not to_addr:
        return JsonResponse({'success': False, 'error': 'recipient_missing'}, status=400)

    # Build template context and render HTML email using the same template
    subscriber_name = to_addr.split('@')[0].replace('.', ' ').replace('_', ' ').title()
    your_brand_name = getattr(settings, 'BRAND_NAME', 'FreshHarvest')
    tpl_ctx = {
        'subscriber_name': subscriber_name,
        'cta_link': request.build_absolute_uri('/'),
        'your_brand_name': your_brand_name,
        'year': timezone.now().year,
        'unsubscribe_link': request.build_absolute_uri('/'),
    }

    # If admin requested welcome template, let template show default welcome content
    if template_flag == 'welcome':
        if not subject:
            subject = f"Welcome to {your_brand_name} — Thanks for subscribing"
        tpl_ctx['custom_body_html'] = None
    else:
        # Embed provided body into the template's content area
        from django.utils.html import escape
        safe_html = ''
        if body:
            safe_html = '<p>' + escape(body).replace('\n', '<br>') + '</p>'
        tpl_ctx['custom_body_html'] = safe_html

    try:
        html_content = render_to_string('email_template.html', tpl_ctx)
    except Exception:
        html_content = tpl_ctx.get('custom_body_html') or (body or '')

    text_content = strip_tags(html_content) if html_content else (body or '')

    # Friendly from name
    from_addr = getattr(settings, 'EMAIL_HOST_USER', None)
    from_email = f"{your_brand_name} Team <{from_addr}>" if from_addr else None

    try:
        msg = EmailMultiAlternatives(subject=subject or '', body=text_content, from_email=from_email, to=[to_addr])
        if html_content:
            msg.attach_alternative(html_content, 'text/html')

        # attachments
        for f in request.FILES.getlist('attachments'):
            try:
                file_content = f.read()
                msg.attach(f.name, file_content, f.content_type or 'application/octet-stream')
            except Exception:
                continue

        msg.send()
        return JsonResponse({'success': True})
    except Exception as exc:
        return JsonResponse({'success': False, 'error': str(exc)}, status=500)

def delete_subscriber(request, subscriber_id):
    if not request.session.get('adminid'):
        messages.error(request, "You are not logged in")
        return redirect('adminlogin')
    try:
        sub = Subscriber.objects.get(pk=subscriber_id)
        sub.delete()
        messages.success(request, "Subscriber deleted.")
    except Subscriber.DoesNotExist:
        messages.error(request, "Subscriber not found.")
    return redirect('view_subscribed')