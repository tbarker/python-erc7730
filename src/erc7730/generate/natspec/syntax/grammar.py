"""Grammar for the values of clearsig annotations, not Solidity comments."""

GRAMMAR = r"""
    pairs: ","* (pair ","*)*
    pair: TARGET "=" value
    value: piece+
    ?piece: STRING | BARE | VALUE_COMMA | square | brace | paren
    VALUE_COMMA: /,(?![\s,]*(?:[^\s,=]+\s*=|$))/
    square: "[" inner* "]"
    brace: "{" inner* "}"
    paren: "(" inner* ")"
    ?inner: STRING | INNER | BARE | "," | VALUE_COMMA | square | brace | paren
    // A new name= starts an assignment only at a whitespace/comma boundary.
    // Inside quotes or balanced values, it remains literal content.
    TARGET.2: /(?<![^\s,])[^\s,="{}()]+(?=\s*=)/
    BARE: /(?!(?<![^\s,])[^\s,=]+\s*=)[^\s,"\[\]{}()]+/
    INNER: /[^\s"\[\]{}()]+/

    constants: (constant ","*)*
    constant: NAME "=" json
    enums: (enum ","*)*
    enum: enum_target "[" ORDINAL "]" "=" json
    enum_target: ENUM_NAME ("[" INDEX? "]" ENUM_NAME)*
    ENUM_NAME: /[^\s,=\[\]]+/
    INDEX: /[^\s,=\[\]]+/
    ORDINAL: /[0-9]+/
    ?json: STRING | SIGNED_NUMBER | "true" | "false" | "null" | "NaN" | "Infinity" | "-Infinity"
         | json_array | json_object
    json_array: "[" [json ("," json)*] "]"
    json_object: "{" [STRING ":" json ("," STRING ":" json)*] "}"

    groups: ";"* (group ";"*)*
    group: NAME label? "fields" "=" "(" members ")" iteration?
    label: "=" STRING
    members: [MEMBER ("," MEMBER)*]
    iteration: "iteration" "=" NAME
    MEMBER: /[^\s,()]+/

    map_target: NAME "[" MAP_KEY "]"
    MAP_KEY: /[^\[\]]+/
    map_expression: "map" "(" NAME "," KEY_PATH ")"
    map_ref: PARAMETER ":" NAME "(" KEY_PATH ")"
    PARAMETER: /[A-Za-z]+/
    KEY_PATH: /[^()]+/
    NAME: /[A-Za-z_][A-Za-z0-9_]*/
    %import common.ESCAPED_STRING -> STRING
    %import common.SIGNED_NUMBER
    %import common.WS
    %ignore WS
"""
