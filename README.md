# FreshHarvest – Inventory & Product Management System

FreshHarvest is a **Django-based inventory management application** designed for managing products, categories, units, stock levels, offers, and stock history.  
It is ideal for **grocery stores, fresh produce vendors, and small-to-medium retail businesses** requiring precise stock control, including fractional quantities such as kilograms and liters.

---

## 📌 Features Overview

- Product & category management  
- Fractional stock handling (kg / liter / decimal-based)  
- Stock history & audit logs  
- Low-stock alerts  
- Product sub-quantities (variants)  
- Time-based offers & discounts  
- Django admin dashboard  
- SQLite database (default)

---

## 🧩 Tech Stack

- **Backend:** Django (Python)
- **Database:** SQLite (default)
- **Frontend:** Django Templates + Static Assets
- **ORM:** Django ORM

---

## 📂 Project Structure

```
freshHarvest/
├── manage.py
├── db.sqlite3
├── adminapp/
│   ├── models.py
│   ├── views.py
│   ├── admin.py
│   ├── stock_utils.py
│   ├── adminappurls.py
│   ├── migrations/
│   ├── static/
│   └── templates/
└── myproject/
    ├── settings.py
    ├── urls.py
    └── wsgi.py
```

---

## 🧠 Core Functionalities

### 1. Category Management
- Create and manage product categories
- Optional category descriptions
- Used for product organization

### 2. Unit Management
- Define measurement units (Kg, Liter, Piece, etc.)
- Units linked directly to products
- Supports flexible inventory measurements

### 3. Product Management
Each product supports:
- Title & description
- Category & unit mapping
- Original price & selling price
- Image upload
- Published date
- Fractional stock quantities
- Maximum stock limit
- Automatic stock update timestamps

### 4. Fractional Stock Handling
- Uses Decimal fields
- Accurate inventory tracking for:
  - Fruits
  - Vegetables
  - Liquids
- Avoids floating-point rounding errors

### 5. Stock History Tracking
- Logs every stock change
- Includes:
  - Product reference
  - Quantity added or removed
  - Reason for change
  - Timestamp
- Useful for auditing and reconciliation

### 6. Low Stock Alerts
- Detects low inventory levels
- Helps prevent out-of-stock situations
- Extendable to email or notifications

### 7. Product Sub-Quantities
- Supports multiple pack sizes
- Examples:
  - 250g / 500g / 1kg
- Automatically adjusts base stock

### 8. Offer & Discount Management
- Start and end date & time
- Active/inactive state handling
- Automatic validity checks
- Suitable for promotions and flash sales

### 9. Admin Dashboard
- Django Admin integration
- Product, stock, unit, and offer control
- Clean UI with static assets

---

## ⚙️ Installation & Setup

### 1. Clone the Repository
```bash
git clone <repository-url>
cd freshHarvest
```

### 2. Create Virtual Environment
```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
```

### 3. Install Dependencies
```bash
pip install django
```

### 4. Run Migrations
```bash
python manage.py migrate
```

### 5. Create Superuser
```bash
python manage.py createsuperuser
```

### 6. Start Development Server
```bash
python manage.py runserver
```

---

## 🔐 Admin Panel Access

```
http://127.0.0.1:8000/admin/
```

---

## 📈 Use Cases

- Grocery inventory management
- Fresh produce stock tracking
- Retail inventory monitoring
- Discount & offer scheduling
- Stock auditing and reporting

---

## 🚀 Future Enhancements

- REST API (Django REST Framework)
- Sales & order management
- Customer-facing storefront
- Email/SMS notifications
- Role-based access control
- PostgreSQL / MySQL support

---

## 📄 License

This project is intended for educational and internal business use.  
Add a license file before public distribution.
