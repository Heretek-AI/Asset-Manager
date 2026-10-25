# Action manifest schema (`*.yaml`)

Every key below was seen in shipped manifests (101 files surveyed). The host
accepts exactly these; unknown `register` triggers are rejected, everything
else forwards untouched.

```yaml
version: "1.0"          # manifest schema; "1.0" or 1
action:
  name: Hello World     # required, display string
  id: example::hello    # required, namespaced (ap:: / git:: / <domain>::)
  version: 1            # action version (int)
  author: Heretek-AI
  category: examples     # free-form path: user, vc, git, video, image, ...
  type: python          # required: python | command | package
  description: What it does (may contain HTML links)
  enable: true          # bool, or hook-module name for dynamic visibility
  icon:                 # optional
    path: icons/hi.svg  # :/icons/** builtin | :icons/** alias | relative path
    color: white        # optional tint key
  script: hello.py      # python: .py file, or "none" (host-wired placeholder)
  command: code         # command: executable
  arguments: ${path}    # command: args template
  workingDirectory: ${path}   # command: cwd template
  detach: true          # command: standalone lifetime
  environment:          # command: VAR map, ${VAR} expansion incl. ${PATH}
    MY_VAR: value
  inputs:               # literal defaults, or prompt-maps:
    fps: "25"           #   {message, default, browse: file|folder,
    shot:               #    store: user|action|project}
      message: Pick a shot
      browse: folder
      store: project
  settings: gui.py      # optional settings-module .py
  dependencies: [util.py]  # extra files staged with the action
  platforms: [win]      # optional OS restriction
  actions: [a::one]     # package: member action ids
  toast:                # optional
    error:
      message: Could not launch editor
  register:             # where the action appears (bool or {enable, filter})
    file: {enable: true, filter: "*.png;*.jpg"}
    folder: {enable: true}
    new_file: {enable: true}
    new_folder: {enable: true}
    new_task: {enable: true}
    task: {enable: true}
    sidebar: {enable: true}
    workspace_overview: {enable: true}
    join_project_files: {enable: true}
    drive: {enable: false}
```

`${name}` variables expand in `arguments`, `workingDirectory`, `environment`,
`command` and `inputs` values. Unknown names are left intact. Observed:
`${path}`, `${yaml_dir}`, `${username}`, `${command_to_run}`, `${PATH}`,
`${custom_path}` plus environment passthrough.
