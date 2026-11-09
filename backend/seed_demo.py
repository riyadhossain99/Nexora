import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nexora.settings")
django.setup()

from django.contrib.auth.models import User

from core.models import Conversation, Order, Product, SystemConfig, Tenant

IMG = "https://images.unsplash.com/photo-{id}?w=800&q=80&auto=format&fit=crop"

admin_user = os.environ.get("ADMIN_USER", "admin")
admin_pass = os.environ.get("ADMIN_PASS", "Admin123")
admin_email = os.environ.get("ADMIN_EMAIL", "Nexoraagent@proton.me")

SHOPS = [
    {
        "username": "zara",
        "password": os.environ.get("ZARA_PASS", "Zara1234"),
        "business_name": "Zara Fashion",
        "email": "zara@example.com",
        "plan": "PRO",
        "settings": {
            "greeting": "Welcome to Zara Fashion! Tell me what you are looking for and I will check sizes, colors and stock.",
            "commands": [
                {"trigger": "delivery", "reply": "Delivery inside Dhaka takes 2 days (৳80); outside Dhaka 3-5 days."},
                {"trigger": "size", "reply": "Tell me the product and I will share the size guide for that item."},
            ],
        },
        "products": [
            {
                "name": "Satin Wrap Dress",
                "description": "Flowing satin wrap dress with tie waist, midi length.",
                "base_price": 2490,
                "image_url": IMG.format(id="1572804013309-59a88b7e92f1"),
                "skus": [
                    {"sku": "ZF-DRS-RED-S", "size": "S", "color": "Red", "price": 2490, "stock": 6},
                    {"sku": "ZF-DRS-RED-M", "size": "M", "color": "Red", "price": 2490, "stock": 9},
                    {"sku": "ZF-DRS-BLK-L", "size": "L", "color": "Black", "price": 2590, "stock": 4},
                ],
            },
            {
                "name": "Cream Knit Poncho",
                "description": "Soft fringed knit poncho in cream, one layer, cozy drape.",
                "base_price": 1690,
                "image_url": IMG.format(id="1434389677669-e08b4cac3105"),
                "skus": [
                    {"sku": "ZF-KNT-CRM-S", "size": "S", "color": "Cream", "price": 1690, "stock": 10},
                    {"sku": "ZF-KNT-CRM-M", "size": "M", "color": "Cream", "price": 1690, "stock": 14},
                    {"sku": "ZF-KNT-OAT-M", "size": "M", "color": "Oat", "price": 1750, "stock": 7},
                ],
            },
            {
                "name": "High-Rise Skinny Jeans",
                "description": "Stretch denim with high-rise fit, ankle length, light blue wash.",
                "base_price": 1890,
                "image_url": IMG.format(id="1584370848010-d7fe6bc767ec"),
                "skus": [
                    {"sku": "ZF-JNS-BLU-28", "size": "28", "color": "Light Blue", "price": 1890, "stock": 8},
                    {"sku": "ZF-JNS-BLU-30", "size": "30", "color": "Light Blue", "price": 1890, "stock": 12},
                    {"sku": "ZF-JNS-BLU-32", "size": "32", "color": "Light Blue", "price": 1890, "stock": 5},
                ],
            },
            {
                "name": "Double-Breasted Trench Coat",
                "description": "Belted trench coat in beige, storm flap and epaulettes.",
                "base_price": 4590,
                "image_url": IMG.format(id="1539533018447-63fcce2678e3"),
                "skus": [
                    {"sku": "ZF-TRC-BEI-S", "size": "S", "color": "Beige", "price": 4590, "stock": 4},
                    {"sku": "ZF-TRC-BEI-M", "size": "M", "color": "Beige", "price": 4590, "stock": 6},
                ],
            },
            {
                "name": "Structured Shoulder Bag",
                "description": "Compact structured bag with metallic clasp and chain strap.",
                "base_price": 2190,
                "image_url": IMG.format(id="1584917865442-de89df76afd3"),
                "skus": [
                    {"sku": "ZF-BAG-RED-STD", "size": "One Size", "color": "Red", "price": 2190, "stock": 10},
                    {"sku": "ZF-BAG-BLK-STD", "size": "One Size", "color": "Black", "price": 2190, "stock": 8},
                ],
            },
            {
                "name": "Cotton Crew Tee (Legacy)",
                "description": "Discontinued basic crew tee, kept for reference.",
                "base_price": 690,
                "image_url": IMG.format(id="1581655353564-df123a1eb820"),
                "is_active": False,
                "skus": [
                    {"sku": "ZF-TEE-WHT-M", "size": "M", "color": "White", "price": 690, "stock": 0},
                    {"sku": "ZF-TEE-WHT-L", "size": "L", "color": "White", "price": 690, "stock": 2},
                ],
            },
        ],
        "orders": [
            {
                "customer_phone": "8801811000001",
                "customer_name": "Nusrat Jahan",
                "address": "House 12, Road 5, Dhanmondi, Dhaka",
                "items": [{"sku": "ZF-DRS-BLK-L", "qty": 1, "product": "Satin Wrap Dress", "price": 2590}],
                "total": 2590,
                "status": "SHIPPED",
                "shipment": {"courier": "PATHAO", "consignment": "PTH-220145", "status": "simulated"},
            },
            {
                "customer_phone": "8801811000002",
                "customer_name": "Rafi Ahmed",
                "address": "Banani, Dhaka",
                "items": [{"sku": "ZF-BAG-RED-STD", "qty": 1, "product": "Structured Shoulder Bag", "price": 2190}],
                "total": 2190,
                "status": "PENDING",
            },
        ],
        "conversations": [
            {
                "customer_phone": "8801811000001",
                "customer_name": "Nusrat Jahan",
                "messages": [
                    {"role": "user", "content": "Do you have the satin dress in black?"},
                    {
                        "role": "assistant",
                        "content": "Yes, ZF-DRS-BLK-L is in stock at ৳2590. Want me to place an order?",
                    },
                    {"role": "user", "content": "Yes, deliver to Dhanmondi"},
                ],
            },
            {
                "customer_phone": "8801811000003",
                "customer_name": "Sadia Islam",
                "needs_human": True,
                "messages": [
                    {"role": "user", "content": "Can you restock the cream poncho in oat?"},
                    {"role": "assistant", "content": "That is a stock request, I have asked the shop team to help you."},
                ],
            },
        ],
    },
    {
        "username": "mrperfect",
        "password": os.environ.get("MRPERFECT_PASS", "Perfect1"),
        "business_name": "Mr Perfect",
        "email": "mrperfect@example.com",
        "plan": "PLUS",
        "settings": {
            "greeting": "Welcome to Mr Perfect! Looking for formals? I can check sizes, colors and stock right away.",
            "commands": [
                {"trigger": "delivery", "reply": "Same-day delivery inside Dhaka if ordered before 2pm (৳100)."},
                {"trigger": "tailor", "reply": "Basic alterations are free. Custom tailoring takes 5 days."},
            ],
        },
        "products": [
            {
                "name": "Slim-Fit Polo Shirt",
                "description": "Combed cotton polo with ribbed collar, slim fit.",
                "base_price": 1190,
                "image_url": IMG.format(id="1602810318383-e386cc2a3ccf"),
                "skus": [
                    {"sku": "MP-POL-WHT-M", "size": "M", "color": "White", "price": 1190, "stock": 10},
                    {"sku": "MP-POL-NVY-M", "size": "M", "color": "Navy", "price": 1190, "stock": 12},
                    {"sku": "MP-POL-MRN-L", "size": "L", "color": "Maroon", "price": 1190, "stock": 8},
                ],
            },
            {
                "name": "Classic Denim Shirt",
                "description": "Washed denim shirt with button-down collar and chest pockets.",
                "base_price": 1490,
                "image_url": IMG.format(id="1596755094514-f87e34085b2c"),
                "skus": [
                    {"sku": "MP-SHT-DNM-M", "size": "M", "color": "Denim Blue", "price": 1490, "stock": 9},
                    {"sku": "MP-SHT-DNM-L", "size": "L", "color": "Denim Blue", "price": 1490, "stock": 7},
                ],
            },
            {
                "name": "Slim-Fit Business Suit",
                "description": "Two-piece suit in navy with tailored cut, notch lapel.",
                "base_price": 6490,
                "image_url": IMG.format(id="1507679799987-c73779587ccf"),
                "skus": [
                    {"sku": "MP-SUI-NVY-40", "size": "40", "color": "Navy", "price": 6490, "stock": 5},
                    {"sku": "MP-SUI-NVY-42", "size": "42", "color": "Navy", "price": 6490, "stock": 3},
                ],
            },
            {
                "name": "Classic Analog Watch",
                "description": "Stainless steel case with leather strap and mineral glass.",
                "base_price": 3290,
                "image_url": IMG.format(id="1524805444758-089113d48a6d"),
                "skus": [
                    {"sku": "MP-WCH-BLK-STD", "size": "One Size", "color": "Black", "price": 3290, "stock": 6},
                    {"sku": "MP-WCH-RGD-STD", "size": "One Size", "color": "Rose Gold", "price": 3490, "stock": 4},
                ],
            },
            {
                "name": "Leather Formal Shoes",
                "description": "Genuine leather derby shoes with cushioned insole.",
                "base_price": 2690,
                "image_url": IMG.format(id="1560769629-975ec94e6a86"),
                "skus": [
                    {"sku": "MP-SHO-BRN-41", "size": "41", "color": "Brown", "price": 2690, "stock": 8},
                    {"sku": "MP-SHO-BRN-42", "size": "42", "color": "Brown", "price": 2690, "stock": 10},
                    {"sku": "MP-SHO-TAN-42", "size": "42", "color": "Tan", "price": 2790, "stock": 5},
                ],
            },
            {
                "name": "Suede Loafers (Legacy)",
                "description": "Discontinued suede loafers from last season.",
                "base_price": 2990,
                "image_url": IMG.format(id="1533867617858-e7b97e060509"),
                "is_active": False,
                "skus": [
                    {"sku": "MP-LOA-TAN-41", "size": "41", "color": "Tan", "price": 2990, "stock": 1},
                    {"sku": "MP-LOA-BRN-42", "size": "42", "color": "Brown", "price": 2990, "stock": 0},
                ],
            },
        ],
        "orders": [
            {
                "customer_phone": "8801911000001",
                "customer_name": "Kamal Hossain",
                "address": "Gulshan 2, Dhaka",
                "items": [{"sku": "MP-WCH-BLK-STD", "qty": 1, "product": "Classic Analog Watch", "price": 3290}],
                "total": 3290,
                "status": "COMPLETED",
            },
            {
                "customer_phone": "8801911000002",
                "customer_name": "Tanvir Islam",
                "address": "Mirpur 10, Dhaka",
                "items": [
                    {"sku": "MP-POL-NVY-M", "qty": 2, "product": "Slim-Fit Polo Shirt", "price": 1190},
                    {"sku": "MP-SHT-DNM-M", "qty": 1, "product": "Classic Denim Shirt", "price": 1490},
                ],
                "total": 3870,
                "status": "ACCEPTED",
            },
        ],
        "conversations": [
            {
                "customer_phone": "8801911000001",
                "customer_name": "Kamal Hossain",
                "messages": [
                    {"role": "user", "content": "Is the black analog watch available?"},
                    {
                        "role": "assistant",
                        "content": "Yes, MP-WCH-BLK-STD is in stock at ৳3290. Would you like me to place an order?",
                    },
                    {"role": "user", "content": "Yes, deliver to Gulshan 2"},
                ],
            },
            {
                "customer_phone": "8801911000003",
                "customer_name": "Arif Chowdhury",
                "needs_human": True,
                "messages": [
                    {"role": "user", "content": "Can you tailor the navy suit sleeves for me?"},
                    {"role": "assistant", "content": "That is a tailoring request, I have asked the shop to help you."},
                ],
            },
        ],
    },
]


def seed_admin():
    user, created = User.objects.get_or_create(username=admin_user)
    if not created:
        print(f"kept existing admin: {admin_user}")
        return
    user.is_staff = True
    user.is_superuser = True
    user.email = admin_email
    user.set_password(admin_pass)
    user.save()
    print(f"created admin: {admin_user}")


def seed_shop(shop):
    user, created = User.objects.get_or_create(username=shop["username"])
    if not created:
        print(f"kept existing shop: {shop['username']}")
        return
    user.email = shop["email"]
    user.set_password(shop["password"])
    user.save()

    tenant = Tenant.objects.create(
        user=user,
        business_name=shop["business_name"],
        plan=shop["plan"],
        settings=shop["settings"],
    )

    for product in shop["products"]:
        Product.objects.create(tenant=tenant, **product)

    for order in shop["orders"]:
        Order.objects.create(tenant=tenant, **order)

    for conv in shop["conversations"]:
        Conversation.objects.create(tenant=tenant, **conv)

    active = sum(1 for p in shop["products"] if p.get("is_active", True))
    print(
        f"{'created' if created else 'updated'} shop '{tenant.business_name}': "
        f"{shop['username']} — "
        f"{active} active + {len(shop['products']) - active} archived products, "
        f"{len(shop['orders'])} orders, {len(shop['conversations'])} conversations, plan {shop['plan']}"
    )


if __name__ == "__main__":
    from django.db import transaction

    with transaction.atomic():
        seed_admin()
        SystemConfig.load()
        for shop in SHOPS:
            seed_shop(shop)
    print("Demo setup complete; existing accounts and data were kept.")
