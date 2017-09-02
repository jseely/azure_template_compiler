#!/usr/bin/env python3
import argparse
import copy
import json
import os
import sys

def replaceString(obj, origString, newString):
    content = json.dumps(obj, indent=4)
    content = content.replace(origString, newString)
    return json.loads(content)

def compile_template_reference(basePath, resource, next_namespace):
    if not "type" in resource: 
        raise Exception("Parameter is not a valid resource file")
    if resource["type"] != "Microsoft.Resources/deployments":
        raise Excpetion("Resource is not a template reference")
    if not "relativePath" in resource["properties"]["templateLink"]:
        print("Warning template reference with name '" + resource["name"] + "' does not contain a relative path. Including as standard template deployment reference.", file=sys.stderr)
        return {}, [copy.deepcopy(resource)], {}, next_namespace

    variables = {}
    resources = []
    outputs = {}
    cur_namespace = next_namespace
    next_namespace = next_namespace + 1

    templatePath = os.path.join(basePath, resource["properties"]["templateLink"]["relativePath"])
    with open(templatePath) as templateFile:
        referencedTemplate = json.load(templateFile)
        compiledReferencedTemplate = compile_template(os.path.dirname(templatePath), referencedTemplate)
        # Because parameters provided to referenced templates can be dynamically generated in the base template,
        # all parameters in referenced templates need to be changed to variables.
        compiledReferencedTemplate = replaceString(compiledReferencedTemplate, "parameters(", "variables(")

    # Add defaultValue parameters to variables list
    if "parameters" in compiledReferencedTemplate:
        pNames = compiledReferencedTemplate["parameters"].keys()
        for pName in pNames:
            if "defaultValue" in compiledReferencedTemplate["parameters"][pName]:
                variables[str(cur_namespace) + "-" + pName] = copy.deepcopy(compiledReferencedTemplate["parameters"][pName]["defaultValue"])
            # Update references in template with new name and reload config
            compiledReferencedTemplate = replaceString(compiledReferencedTemplate, "variables('{}')".format(pName), "variables('{}-{}')".format(cur_namespace, pName))

    # Add provided parameters, overriding defaultValues if they exist
    if "parameters" in resource["properties"]:
        for k, v in resource["properties"]["parameters"].items():
            variables[str(cur_namespace) + "-" + k] = copy.deepcopy(v["value"])

    # Add variables from referenced template
    if "variables" in compiledReferencedTemplate:
        vNames = compiledReferencedTemplate["variables"].keys()
        for vName in vNames:
            variables[str(cur_namespace) + "-" + vName] = copy.deepcopy(compiledReferencedTemplate["variables"][vName]["value"])
            # Update references in template with new name and reload config
            compiledReferencedTemplate = replaceString(compiledReferencedTemplate, "variables('{}')".format(vName), "variables('{}-{}')".format(cur_namespace, vName))

    # Add resources from referenced template
    for resource in compiledReferencedTemplate["resources"]:
        resourceCopy = copy.deepcopy(resource)
        if resource["name"].startswith("["):
            name = "[concat('{}-', {})]".format(cur_namespace, resource["name"][1:-1])
        else:
            name = "{}-{}".format(cur_namespace, resource["name"])
        resourceCopy["name"] = name
        resources.append(resourceCopy)

    return variables, resources, outputs, next_namespace

def dependency_name(resource):
    if resource["type"].startswith("[") or resource["name"].startswith("["):
        if resource["type"].startswith("["):
            type = resource["type"][1:-1]
        else:
            type = "'{}'".format(resource["type"])
        
        if resource["name"].startswith("["):
            name = resource["name"][1:-1]
        else:
            name = "'{}'".format(resource["name"])
        return "[concat({}, '/', {})]".format(type, name)
    else:
        return "{}/{}".format(resource["type"], resource["name"])

def compile_template(basePath, template):
    compiled_template = {}
    compiled_template["contentVersion"] = template["contentVersion"]
    compiled_template["$schema"] = template["$schema"]

    # Copy base template parameters
    if "parameters" in template:
        compiled_template["parameters"] = copy.deepcopy(template["parameters"])

    # Add all base template variables with namespace "0"
    if "variables" in template:
        compiled_template["variables"] = copy.deepcopy(template["variables"])

    # Add all base template resources
    next_namespace = 1
    deploymentDependencies = {}
    resourcesWaitingDepencencies = {}
    compiled_template["resources"] = []
    for resource in template["resources"]:
        if resource["type"] == "Microsoft.Resources/deployments":
            variables, resources, outputs, next_namespace = compile_template_reference(basePath, resource, next_namespace)
            for k, v in variables.items():
                compiled_template["variables"][k] = v
            compiled_template["resources"].extend(resources)
            
            # Update dependsOn for resources with a dependency on this deployment
            dDeps = [ dependency_name(r) for r in resources ]
            dRef = dependency_name(resource)
            # Update dependsOn for resources that have already been added to the compiled_template
            if dRef in resourcesWaitingDepencencies:
                for r in resourcesWaitingDepencencies[dRef]:
                    r["dependsOn"].extend(dDeps)
            # Save dependency map for future resources
            deploymentDependencies[dRef] = dDeps
        else:
            resourceCopy = copy.deepcopy(resource)
            if "dependsOn" in resourceCopy:
                # The resource has dependencies, we need to make sure all deployment dependencies get expanded to cover all deployment resources
                origDepends = resourceCopy["dependsOn"]
                resourceCopy["dependsOn"] = []
                for ref in origDepends:
                    if "Microsoft.Resources/deployments" in ref:
                        if ref in deploymentDependencies:
                            # Reference is a deployment and it has already been processed
                            resourceCopy["dependsOn"].extend(deploymentDependencies[ref])
                        else:
                            # Reference is a deployment and it hasn't been processed (add to list to expand later)
                            if ref in resourcesWaitingDepencencies:
                                resourcesWaitingDepencencies[ref].append(resourceCopy)
                            else:
                                resourcesWaitingDepencencies[ref] = [resourceCopy]
                    else:
                        # Reference isn't a deployment, just add it
                        resourceCopy["dependsOn"].append(ref)
            compiled_template["resources"].append(resourceCopy)
    return compiled_template

def main():
    parser = argparse.ArgumentParser(description="Client side compiler for Azure ARM templates")
    parser.add_argument("-f", "--template-file", dest="file", required=True, help="The base ARM template to be compiled")
    args = parser.parse_args()

    basePath = os.path.dirname(os.path.realpath(args.file))

    with open(args.file) as file:
        json_content = json.load(file)
    compiled_template = compile_template(basePath, json_content)
    print(json.dumps(compiled_template, indent=4))

main()
