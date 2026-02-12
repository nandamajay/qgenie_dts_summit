import re

def parse_dtsi_to_mermaid(content):
    lines = content.splitlines()
    stack = []
    edges = []
    
    # Init Graph: useMaxWidth: false prevents shrinking
    graph = [
        "%%{init: {'flowchart': {'useMaxWidth': false, 'htmlLabels': true}}}%%",
        "graph TD"
    ]
    
    # Regex for "label: name {" or "name {"
    node_re = re.compile(r'^(\s*)(?:([\w@-]+):)?\s*([/&\w@-]+)\s*\{')

    for i, line in enumerate(lines):
        line = line.split('//')[0].rstrip() # Ignore comments
        match = node_re.search(line)
        
        if match:
            indent, label, name = match.groups()
            display_name = label if label else name
            node_id = f"N{i}"  # Unique ID based on line number
            
            # Create Node
            graph.append(f"    {node_id}[\"{display_name}\"]")
            
            # Create Edge from Parent
            if stack:
                parent_id = stack[-1]['id']
                graph.append(f"    {parent_id} --> {node_id}")
            
            stack.append({'id': node_id})
            
        if '};' in line:
            if stack:
                stack.pop()
                
    if len(graph) == 2:
        return "graph TD;\nError[No Structure Found]"
        
    return "\n".join(graph)
