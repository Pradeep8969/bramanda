from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.utils import timezone
from django.db import DatabaseError
from products.models import Category, Product, Size, Color, ProductVariant
from orders.models import Order, OrderItem
from inventory.models import InventoryTransaction
from dashboard.models import StaffActivity


class OwnerTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model().objects
        cls.owner = users.create_user(username='owner', password='Owner-test-893!', role='OWNER')
        cls.staff = users.create_user(username='staff', role='STAFF')
        cls.customer = users.create_user(username='customer')
        cls.category = Category.objects.create(name='Clothing')
        cls.product = Product.objects.create(name='Shirt', category=cls.category, price=100)
        cls.size = Size.objects.create(name='M')
        cls.color = Color.objects.create(name='Black')
        cls.variant = ProductVariant.objects.create(product=cls.product, size=cls.size, color=cls.color, sku='SH-M', stock_quantity=5)
        cls.order = cls.make_order(200, payment_status='PAID', order_status='DELIVERED')
        cls.pending = cls.make_order(100, order_status='PENDING')
        cls.cancelled = cls.make_order(900, payment_status='PAID', order_status='CANCELLED')
        for order, quantity in [(cls.order, 2), (cls.pending, 1), (cls.cancelled, 9)]:
            OrderItem.objects.create(order=order, product=cls.product, variant=cls.variant,
                product_name='Old Shirt', size_name='M', color_name='Black', sku='SH-M', quantity=quantity,
                unit_price=100, subtotal=quantity*100)

    @classmethod
    def make_order(cls, total, **kwargs):
        return Order.objects.create(customer=cls.customer, first_name='A', last_name='B', email='a@b.com',
            phone_number='98', shipping_address='Kathmandu', subtotal=total, shipping_cost=0, grand_total=total, **kwargs)

    def setUp(self):
        self.client.force_login(self.owner)
        self.detail = f'/owner/orders/{self.order.order_number}/'

    def pages(self):
        return ['/owner/', '/owner/reports/', '/owner/staff/', '/owner/staff/add/',
            f'/owner/staff/{self.staff.pk}/edit/', '/owner/payments/', '/owner/activity/', '/owner/customers/',
            '/owner/inventory/', '/owner/orders/', self.detail] + [url for kind in
            ['products', 'categories', 'sizes', 'colors', 'variants'] for url in
            [f'/owner/{kind}/', f'/owner/{kind}/add/']]

    def mutations(self):
        return [(f'/owner/products/{self.product.pk}/toggle/', {}),
            (f'/owner/categories/{self.category.pk}/toggle/', {}),
            (f'/owner/staff/{self.staff.pk}/toggle/', {}),
            ('/owner/products/add/', self.product_data()), ('/owner/staff/add/', self.staff_data()),
            ('/owner/inventory/adjust/', self.adjustment()),
            (self.detail+'status/', {'order_status':'PROCESSING'}),
            (self.detail+'delivery/', {'delivery_status':'SHIPPED'}),
            (self.detail+'payment/', {'payment_status':'PAID'})]

    def product_data(self, **kwargs):
        data = {'name':'New Shirt', 'category':self.category.pk, 'price':'250.00', 'is_active':'on'}
        data.update(kwargs)
        return data

    def staff_data(self, **kwargs):
        data = {'username':'newstaff', 'password1':'Staff-password-783!', 'password2':'Staff-password-783!', 'is_active':'on', 'role':'OWNER', 'is_superuser':'on'}
        data.update(kwargs)
        return data

    def adjustment(self, quantity=3):
        return {'variant':self.variant.pk, 'quantity_change':quantity, 'note':'Owner verification'}

    def test_anonymous_access(self):
        self.client.logout()
        for url in self.pages():
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302, url)
            self.assertTrue(response.url.startswith('/login/?next='))
        for url, data in self.mutations():
            self.assertEqual(self.client.post(url,data).status_code,302,url)

    def test_customer_denied_every_route(self):
        self.client.force_login(self.customer)
        for url in self.pages():
            self.assertEqual(self.client.get(url).status_code,403,url)
        for url, data in self.mutations():
            self.assertEqual(self.client.post(url,data).status_code,403,url)

    def test_staff_denied_every_route(self):
        self.client.force_login(self.staff)
        for url in self.pages():
            self.assertEqual(self.client.get(url).status_code,403,url)
        for url, data in self.mutations():
            self.assertEqual(self.client.post(url,data).status_code,403,url)

    def test_owner_all_pages(self):
        for url in self.pages():
            self.assertEqual(self.client.get(url).status_code,200,url)

    def test_superuser_does_not_bypass_role(self):
        self.customer.is_superuser=True
        self.customer.is_staff=True
        self.customer.save()
        self.client.force_login(self.customer)
        self.assertEqual(self.client.get('/owner/').status_code,403)

    def test_dashboard_metrics(self):
        cards=dict(self.client.get('/owner/').context['cards'])
        expected={'Total Revenue':Decimal(200),'Total Orders':3,'Total Customers':1,
            'Total Products':1,'Total Active Products':1,'Pending Orders':1,'Processing Orders':0,
            'Delivered Orders':1,'Paid Orders':2,'Low Stock Variants':1,'Out of Stock Variants':0,
            'Sales Today':Decimal(200),'Sales This Month':Decimal(200),'Orders Today':3,'Orders This Month':3}
        self.assertEqual(cards,expected)

    def test_stock_boundaries(self):
        for stock, low, out in [(0,0,1),(1,1,0),(5,1,0),(6,0,0)]:
            ProductVariant.objects.filter(pk=self.variant.pk).update(stock_quantity=stock)
            cards=dict(self.client.get('/owner/').context['cards'])
            self.assertEqual((cards['Low Stock Variants'],cards['Out of Stock Variants']),(low,out))
        ProductVariant.objects.filter(pk=self.variant.pk).update(is_active=False,stock_quantity=0)
        self.assertEqual(dict(self.client.get('/owner/').context['cards'])['Out of Stock Variants'],0)

    def test_daily_charts(self):
        Order.objects.filter(pk=self.order.pk).update(created_at=timezone.now()-timedelta(days=2))
        daily=self.client.get('/owner/').context['daily']
        self.assertEqual(len(daily),7)
        self.assertEqual(daily[-3]['sales'],Decimal(200))
        self.assertEqual(daily[-1]['sales'],0)
        self.assertEqual(daily[-1]['orders'],2)

    def test_reports_revenue_average_and_counts(self):
        self.make_order(400,payment_status='PAID',order_status='PROCESSING')
        metrics=self.client.get('/owner/reports/').context['metrics']
        self.assertEqual(metrics,{'revenue':Decimal(600),'order_count':3,'average_order_value':Decimal(300),'delivered_count':1,'cancelled_count':1})

    def test_inclusive_date_filters(self):
        date=timezone.localdate()-timedelta(days=2)
        Order.objects.filter(pk=self.order.pk).update(created_at=timezone.now()-timedelta(days=2))
        metrics=self.client.get('/owner/reports/',{'from_date':date.isoformat(),'to_date':date.isoformat()}).context['metrics']
        self.assertEqual(metrics['revenue'],Decimal(200))
        self.assertEqual(metrics['order_count'],1)
        self.assertEqual(metrics['cancelled_count'],0)

    def test_invalid_dates(self):
        for data in [{'from_date':'bad'},{'from_date':'2026-10-06','to_date':'2026-01-01'}]:
            response=self.client.get('/owner/reports/',data)
            self.assertEqual(response.status_code,400)
            self.assertEqual(response.context['metrics']['revenue'],0)

    def test_empty_report(self):
        metrics=self.client.get('/owner/reports/',{'to_date':'2000-01-01'}).context['metrics']
        self.assertTrue(all(value==0 for value in metrics.values()))

    def test_best_sellers_quantity_and_snapshots(self):
        sellers=list(self.client.get('/owner/reports/').context['best_sellers'])
        self.assertEqual((sellers[0]['units_sold'],sellers[0]['revenue'],sellers[0]['name']),(3,Decimal(300),'Shirt'))
        OrderItem.objects.update(product=None)
        self.assertEqual(self.client.get('/owner/reports/').context['best_sellers'][0]['name'],'Old Shirt')

    def test_product_create(self):
        self.assertEqual(self.client.post('/owner/products/add/',self.product_data()).status_code,302)
        product=Product.objects.get(name='New Shirt')
        self.assertEqual(product.price,Decimal(250))
        self.assertTrue(product.slug)

    def test_product_edit(self):
        self.assertEqual(self.client.post(f'/owner/products/{self.product.pk}/edit/',self.product_data(name='Edited')).status_code,302)
        self.product.refresh_from_db()
        self.assertEqual(self.product.name,'Edited')

    def test_product_deactivate(self):
        self.client.post(f'/owner/products/{self.product.pk}/toggle/')
        self.product.refresh_from_db()
        self.assertFalse(self.product.is_active)

    def test_catalog_management(self):
        for kind,data in [('categories',{'name':'Accessories','is_active':'on'}),('sizes',{'name':'XL','display_order':2,'is_active':'on'}),('colors',{'name':'Red','hex_code':'#ff0000','is_active':'on'})]:
            self.assertEqual(self.client.post(f'/owner/{kind}/add/',data).status_code,302)
        self.client.post(f'/owner/categories/{self.category.pk}/toggle/')
        self.category.refresh_from_db()
        self.assertFalse(self.category.is_active)

    def test_variant_cannot_bypass_stock(self):
        data={'product':self.product.pk,'size':self.size.pk,'color':self.color.pk,'sku':'SH-EDIT','is_active':'on','stock_quantity':999}
        self.assertEqual(self.client.post(f'/owner/variants/{self.variant.pk}/edit/',data).status_code,302)
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_quantity,5)
        newsize=Size.objects.create(name='L')
        data.update(size=newsize.pk,sku='SH-L')
        self.assertEqual(self.client.post('/owner/variants/add/',data).status_code,302)
        self.assertEqual(ProductVariant.objects.get(sku='SH-L').stock_quantity,0)
        self.assertFalse(InventoryTransaction.objects.exists())

    def test_create_staff_hashed_and_fixed_role(self):
        self.assertEqual(self.client.post('/owner/staff/add/',self.staff_data()).status_code,302)
        user=get_user_model().objects.get(username='newstaff')
        self.assertEqual(user.role,'STAFF')
        self.assertTrue(user.check_password('Staff-password-783!'))
        self.assertNotEqual(user.password,'Staff-password-783!')
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.is_staff)

    def test_staff_password_validation(self):
        self.assertEqual(self.client.post('/owner/staff/add/',self.staff_data(password1='123',password2='123')).status_code,400)
        self.assertFalse(get_user_model().objects.filter(username='newstaff').exists())

    def test_edit_staff_whitelist(self):
        original=self.staff.password
        self.client.post(f'/owner/staff/{self.staff.pk}/edit/',{'username':'staff','first_name':'Updated','role':'OWNER','password':'hacked','is_active':'on'})
        self.staff.refresh_from_db()
        self.assertEqual((self.staff.first_name,self.staff.role,self.staff.password),('Updated','STAFF',original))

    def test_deactivate_staff(self):
        self.client.post(f'/owner/staff/{self.staff.pk}/toggle/')
        self.staff.refresh_from_db()
        self.assertFalse(self.staff.is_active)

    def test_cannot_edit_owner_or_customer_as_staff(self):
        for user in [self.owner,self.customer]:
            self.assertEqual(self.client.get(f'/owner/staff/{user.pk}/edit/').status_code,404)
            self.assertEqual(self.client.post(f'/owner/staff/{user.pk}/toggle/').status_code,404)

    def test_inventory_adjustment(self):
        self.assertRedirects(self.client.post('/owner/inventory/adjust/',self.adjustment()),'/owner/inventory/')
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_quantity,8)
        record=InventoryTransaction.objects.get()
        self.assertEqual((record.quantity,record.previous_stock,record.new_stock),(3,5,8))
        self.assertEqual(record.created_by,self.owner)
        self.assertEqual(StaffActivity.objects.get().staff,self.owner)

    def test_inventory_negative_rejected(self):
        self.assertEqual(self.client.post('/owner/inventory/adjust/',self.adjustment(-6)).status_code,400)
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_quantity,5)
        self.assertFalse(InventoryTransaction.objects.exists())

    def test_owner_can_adjust_inactive_variant(self):
        ProductVariant.objects.filter(pk=self.variant.pk).update(is_active=False)
        self.assertContains(self.client.get('/owner/inventory/'),'SH-M')
        self.assertEqual(self.client.post('/owner/inventory/adjust/',self.adjustment()).status_code,302)

    def test_inventory_audit_failure_rollback(self):
        with patch('dashboard.views.StaffActivity.objects.create',side_effect=DatabaseError('failure')):
            self.assertEqual(self.client.post('/owner/inventory/adjust/',self.adjustment()).status_code,400)
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_quantity,5)
        self.assertFalse(InventoryTransaction.objects.exists())

    def test_order_operations_reuse_audit_and_protect_totals(self):
        for suffix,data in [('status/',{'order_status':'PROCESSING'}),('delivery/',{'delivery_status':'SHIPPED'}),('payment/',{'payment_status':'PAID'})]:
            data.update(grand_total='1',subtotal='1',customer=self.owner.pk)
            self.assertRedirects(self.client.post(self.detail+suffix,data),self.detail)
        self.order.refresh_from_db()
        self.assertEqual((self.order.order_status,self.order.delivery_status,self.order.grand_total,self.order.customer),('PROCESSING','SHIPPED',Decimal(200),self.customer))
        self.assertEqual(StaffActivity.objects.count(),2)

    def test_order_search_filters(self):
        response=self.client.get('/owner/orders/',{'q':self.order.order_number,'order_status':'DELIVERED'})
        self.assertEqual(list(response.context['orders']),[self.order])

    def test_payments_filters(self):
        self.assertContains(self.client.get('/owner/payments/'),self.order.order_number)
        for query,count in [({'payment_status':'PAID'},2),({'payment_status':'PENDING','payment_method':'COD'},1),({'payment_method':'CARD'},0)]:
            self.assertEqual(self.client.get('/owner/payments/',query).context['orders'].count(),count)

    def test_activity_filtering_readonly(self):
        record=StaffActivity.objects.create(staff=self.staff,action='ORDER_STATUS',description='Processed',reference='TEST')
        self.assertContains(self.client.get('/owner/activity/'),'Processed')
        self.assertEqual(list(self.client.get('/owner/activity/',{'staff':self.staff.pk,'action':'ORDER_STATUS'}).context['activities']),[record])
        self.assertFalse(self.client.get('/owner/activity/',{'staff':'bad'}).context['activities'])
        self.assertFalse(self.client.get('/owner/activity/',{'to_date':'2000-01-01'}).context['activities'])
        self.assertEqual(self.client.post('/owner/activity/',{}).status_code,405)

    def test_customer_counts(self):
        customers=self.client.get('/owner/customers/').context['customers']
        self.assertEqual(customers[0].order_count,3)
        self.assertEqual(customers[0],self.customer)

    def test_post_only_and_csrf(self):
        csrf=Client(enforce_csrf_checks=True)
        csrf.force_login(self.owner)
        for url,data in self.mutations():
            self.assertEqual(csrf.post(url,data).status_code,403,url)
            self.assertEqual(self.client.put(url,data).status_code,405,url)
            if url.endswith(('toggle/','adjust/','status/','delivery/','payment/')):
                self.assertEqual(self.client.get(url).status_code,405,url)
        csrf.get('/owner/products/add/')
        data=self.product_data()
        data['csrfmiddlewaretoken']=csrf.cookies['csrftoken'].value
        self.assertEqual(csrf.post('/owner/products/add/',data).status_code,302)

    def test_navigation(self):
        for user,owner,staff in [(self.owner,True,False),(self.staff,False,True),(self.customer,False,False)]:
            self.client.force_login(user)
            content=self.client.get('/').content.decode()
            self.assertEqual('Owner Dashboard' in content,owner)
            self.assertEqual('Staff Dashboard' in content,staff)

    def test_real_owner_login_journey(self):
        self.client.logout()
        self.assertTrue(self.client.login(username='owner',password='Owner-test-893!'))
        for url in ['/owner/','/owner/reports/','/owner/products/','/owner/inventory/','/owner/staff/','/owner/orders/','/owner/payments/','/owner/activity/']:
            self.assertEqual(self.client.get(url).status_code,200,url)
