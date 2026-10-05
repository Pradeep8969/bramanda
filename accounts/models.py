from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        OWNER = 'OWNER', 'Owner'
        STAFF = 'STAFF', 'Staff'
        CUSTOMER = 'CUSTOMER', 'Customer'

    role = models.CharField(max_length=10, choices=Role.choices, default=Role.CUSTOMER)
    phone_number = models.CharField(max_length=30, blank=True)
    address = models.TextField(blank=True)
