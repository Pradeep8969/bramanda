LOW_STOCK_MAX = 5


def stock_level(quantity):
    if quantity == 0:
        return 'Out of Stock'
    if quantity <= LOW_STOCK_MAX:
        return 'Low Stock'
    return 'In Stock'
