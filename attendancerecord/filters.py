from django.template.defaulttags import register


@register.filter
def subtract(arg1, arg2):
    return arg1 - arg2

@register.filter
def divide_int(arg1, arg2):
    return arg1 // arg2

@register.filter
def element_at_index(array, index):
    return array[index]

@register.filter
def get_item(dictionary, key):
    return dictionary.get(key)

@register.filter
def add_str(arg1, arg2):
    return str(arg1) + str(arg2)

@register.filter
def count_recursive(collection):
    if isinstance(collection, list):
        return len(collection)
    
    total = 0
    for key, inner_collection in collection.items():
        total += count_recursive(inner_collection)
    return total

@register.filter
def iterate_dict(dict):
    return dict.items()