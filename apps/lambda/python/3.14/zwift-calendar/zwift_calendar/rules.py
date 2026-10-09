"""A small parser for observed Zwift access expressions. No eval or execution."""

import json
import operator
import re

from .errors import UnsupportedRule

TOKEN = re.compile(
    r'\s*(\|\||&&|>=|<=|==|!=|[()!<>]|[a-zA-Z_][\w.]*|\d+(?:\.\d+)?|"[^"\\]*")'
)
COMPARE = {
    ">=": operator.ge,
    "<=": operator.le,
    ">": operator.gt,
    "<": operator.lt,
    "==": operator.eq,
    "!=": operator.ne,
}
FIELDS = {
    "profile.playerType",
    "profile.profileId",
    "profile.age",
    "profile.male",
    "subgroup.label",
    "scoring.current",
    "scoring.max30",
}


def parse(expression):
    if (
        not isinstance(expression, str)
        or not expression.strip()
        or len(expression) > 6000
    ):
        raise UnsupportedRule("Unsupported access expression")
    tokens, offset = [], 0
    expression = expression.strip()
    while offset < len(expression):
        match = TOKEN.match(expression, offset)
        if not match:
            raise UnsupportedRule("Unknown access expression token")
        tokens.append(match[1])
        offset = match.end()
    if len(tokens) > 500:
        raise UnsupportedRule("Access expression too complex")
    index = 0

    def atom(depth):
        nonlocal index
        if depth > 30 or index >= len(tokens):
            raise UnsupportedRule("Invalid access expression")
        value = tokens[index]
        index += 1
        if value == "(":
            result = expression_or(depth + 1)
            if index >= len(tokens) or tokens[index] != ")":
                raise UnsupportedRule("Unbalanced access expression")
            index += 1
            return result
        if value == "!":
            return ("not", atom(depth + 1))
        if value in FIELDS:
            return ("field", value)
        if value in ("true", "false") or value.startswith('"') or value[0].isdigit():
            return ("value", json.loads(value))
        raise UnsupportedRule("Unknown access expression field")

    def comparison(depth):
        nonlocal index
        left = atom(depth)
        if index < len(tokens) and tokens[index] in COMPARE:
            operation = tokens[index]
            index += 1
            return (operation, left, atom(depth))
        return left

    def expression_and(depth):
        nonlocal index
        value = comparison(depth)
        while index < len(tokens) and tokens[index] == "&&":
            index += 1
            value = ("and", value, comparison(depth))
        return value

    def expression_or(depth):
        nonlocal index
        value = expression_and(depth)
        while index < len(tokens) and tokens[index] == "||":
            index += 1
            value = ("or", value, expression_and(depth))
        return value

    tree = expression_or(0)
    if index != len(tokens):
        raise UnsupportedRule("Incomplete access expression")
    return tree


def evaluate(tree, values):
    kind = tree[0]
    if kind == "value":
        return tree[1]
    if kind == "field":
        if tree[1] not in values or values[tree[1]] is None:
            raise UnsupportedRule("Required eligibility value unavailable")
        return values[tree[1]]
    if kind == "not":
        return not evaluate(tree[1], values)
    # Evaluate both branches: an unknown requirement must not get hidden by
    # boolean short-circuiting and accidentally grant eligibility.
    left, right = evaluate(tree[1], values), evaluate(tree[2], values)
    if kind == "and":
        return bool(left and right)
    if kind == "or":
        return bool(left or right)
    try:
        return COMPARE[kind](left, right)
    except TypeError:
        raise UnsupportedRule("Invalid eligibility operand types") from None
