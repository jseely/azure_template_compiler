# Azure ARM Template Compiler

This script compiles Azure ARM templates which contain nested templates (or deployment resources) creating a single ARM template file that can be deployed by itself.

The script converts all parameters in nested templates to variables to support the use of the ARM template scripting language in parameter values. It uses namespacing to avoid naming collisions between variables in the base and nested templates.

## Instructions

To use this script you will need to add a field to your `Microsoft.Resources/deployments` references. The resulting resource should look like this:
```
{
  "name": ...,
  "type": "Microsoft.Resources/deployments",
  "properties": {
    ...,
    "templateLink": {
      ...,
      "relativePath": <the path on the local machine to the referenced template>
    },
    ...
  },
  ...
}
```

With the `relativePath` field added you just need to run the compiler, passing in the base template file with the `-f` argument.
```
./compiler.py -f azureDeploy.json
```

## Gotchas

- Currently no effort is made to avoid naming collisions between parameters and variables in nested templates when converting parameters to variables
- Outputs are not currently supported
