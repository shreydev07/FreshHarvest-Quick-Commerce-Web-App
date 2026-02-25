
from django.urls import path
from . import views

urlpatterns = [
    path('userdash/',views.userdash,name='userdash'),
    path('userlogout/',views.userlogout,name='userlogout'),
    path('viewcart/',views.viewcart,name='viewcart'),
    path('addtocart/<id>',views.addtocart,name='addtocart'),
    path('removeitem/<id>',views.removeitem,name='removeitem'),

    path('checkout/',views.checkout,name='checkout'),
    path('payment-success/',views.payment_success,name='payment_success'),
    path('recent-offers-api/', views.recent_offers_api, name='recent_offers_api'),
    path('view-offers/', views.view_user_offers, name='view_user_offers'),
    path('userorders/',views.userorders,name='userorders'),
    path('userprofile/',views.userprofile,name='userprofile'),
    path('editprofile/',views.editprofile,name='editprofile'),
    path('change-password/', views.userchangepassword, name='userchangepassword'),
    path('send-test-email/', views.send_test_email_view, name='send_test_email'),

]