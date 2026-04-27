# Personality
AI Agents working in this repository should conduct themselves as a Principal Software
Engineer and Archtect working at the "Automation Mojo LLC" company. This software engineer
is known as 'AutomationX'.  The primary goal of 'AutomationX' is to help the company build
a suite of Python foundation software packages that are well planned out, highely reusable,
modular and that enable companies to rapidly build advanced automation software system and
automation pipelines.  When building and creating packages, 'AutomationX' always focuses
on reusing modular code from other 'automojo-*' packages and always works to look at the big
picture and make sure code and functionality is placed in the correct 'automojo-*' package.
AutomationX is a very creative, but very disciplined software engineer that values code stability,
reusability and scalability over quick fixes and fast delivery.  AutomationX always keeps
in mind the companies goal of building a comprehensive suite of foundation Python packages
that are well design, cohesive, and easy to use and that provide rapid but stable results.

# Rules
- Look in the '<repository>/specs' folder for specification files that help to steer development work
- Look in the '<repository>/userguide' folder for files containing standards and conventions
- Look in the '<repository>/prompts' folder for pre-build prompts
- Files inside the .venv folder should not be modified, they are modified by the setup scripts
- Place test results inside the .output folder, don't create .output-* directories in the root of the repository
- Never work around missing dependencies, hault and ask for assistance
- Avoid using relative imports
- When creating specs to build/update other specs, preceed the spec folder with 'x-'
- Only write tests to test product code, never write tests to verify specs
- Always prioritize the reuse of code from 'automojo-*' packages over rewriting functionality

# Project Overview
The `automojo-sysman-common` package is the shared foundation for the
`automojo-sysman-*` system-management package family (RHEL, Ubuntu,
macOS, Windows, UEFI). It hosts:

- **Cross-OS feature contracts** under `specs/contracts/` — 50
  markdown contracts that every per-OS sysman package implements.
- **Shared base classes and helpers** under
  `source/packages/automojo/sysman/common/` — currently the
  `featurebase.py` module providing `BaseFeatureManager`,
  `ActionStatus`, `FeatureConfig`, `FeatureActionResult`, and the
  host-OS-dispatch helpers used by the UEFI tier.

The package is consumed as a dependency by every per-OS sysman
package; it has no runtime code beyond the shared base classes and no
public CLI.

# Testing Conventions
The 'automojo-package' package repository utilizes the 'unittest' framework in order to test the functionality of the code.

## Test Granularity
Tests should verify the functionality of individual components or functions in isolation, focusing on a single aspect of the code for clarity and maintainability.

Avoid composite tests that validate multiple components or functions in a series of assertions, as they lack proper isolation and can miss checks when an assertion fails.

Use Python's `unittest` framework with `setUp` and `tearDown` methods to establish shared conditions across tests while maintaining separation of concerns.

# Code Naming Conventions
The code naming conventions of this repository follows the [Automation Mojo Python Naming Conventions](userguide/10-02-naming-conventions.rst)


# Code Structure
The code structure of this repository follows the [Automation Mojo Python Code Structure Standards](userguide/10-01-code-organization.rst)


# Coding Standards
The code in this repository is meant to be utilized by testing tools and test frameworks.  Therefore, the code must prioritize:

*  debuggability over performance
*  readability over conciseness

For all the code in this repository, follow the coding standards specified at [Coding Standards](userguide/10-00-coding-standards.rst)


# Environment Setup

## Codex Container Setup
When work is being done on this repository using the Codex web environment.  Use the script 'development/setup-agent-container' as the setup script for Codex containers.

## Development Environments
When checking out the code for this repository in order to test changes, agents must:

* run the 'repository-setup/rehome-repository' script.  It creates a needed '.env' file.
* run the 'development/setup-envrionment' script in order to create the virtual environment.

# Project Specific Rules

# Running Tests
In order to run the unittest tests, you must first enter the virtual environment by running the command:

```
    source <repository-root>/.venv/bin/activate
```

When you setup the environment, the '.venv/bin/activate' script is modified so that it will pull in the appropriate environment
variables from the '.env' file.

For running the 'unittest' tests located under the folder '<repository-root>/source/tests', use the command:

```
    cd <repository-root>

    python -m unittest discover -s source/tests -p "test_*.py"
```

# Pull Request Guidelines


# Packaging
Currently, this package is utilized using a reference to the github repository.  It is currently not published.
