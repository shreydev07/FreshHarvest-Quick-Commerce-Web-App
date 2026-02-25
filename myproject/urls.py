"""
URL configuration for myproject project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

from mainapp import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('',views.index,name='index'),
    path('about/',views.about,name='about'),
    path('contact/',views.contact,name='contact'),
    path('login/',views.login,name='login'),
    path('register/',views.register,name='register'),
    path('adminlogin/',views.adminlogin,name='adminlogin'),
    path('adminapp/',include('adminapp.adminappurls')),
    path('userapp/',include('userapp.userappurls')),
    path('product_details/<id>',views.product_details,name='product_details'),
    path('products/',views.products,name='products'),
    path('search/', views.product_search, name='product_search'),
    path('tem/', views.tem, name='tem'),
    path('subscribe/', views.subscribe, name='subscribe'),
]

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)