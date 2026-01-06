from alttester import AltDriver
from alttester import By
from alttester import AltKeyCode

alt_driver = AltDriver(host="127.0.0.1", port=13000, timeout=60)

def get_interactable_2d_objects():
    interactable_2d = []
    
    # Component types to search for
    collider_types = [
        ("UnityEngine.BoxCollider2D", "UnityEngine.CoreModule"),
        ("UnityEngine.CircleCollider2D", "UnityEngine.CoreModule"),
        ("UnityEngine.PolygonCollider2D", "UnityEngine.Physics2D"),
    ]
    
    # Method 1: Use By.COMPONENT to find objects directly (more efficient)
    print("🔍 Method 1: Searching for objects with 2D colliders using By.COMPONENT...\n")
    found_any = False
    for collider_type, assembly in collider_types:
        try:
            objects = alt_driver.find_objects(By.COMPONENT, collider_type)
            print(f"   Found {len(objects)} object(s) with {collider_type}")
            
            if objects:
                found_any = True
            
            for obj in objects:
                # If By.COMPONENT found it, the object definitely has the component
                # Try to check if it's enabled, but if we can't access the property, assume it's enabled
                enabled = True
                component_name_used = None
                
                # Try different component name formats (short name first, as it's more common)
                for component_name in [collider_type.split('.')[-1], collider_type]:
                    try:
                        # Try with assembly
                        result = obj.get_component_property(component_name, "enabled", assembly)
                        enabled = str(result).lower() == "true"
                        component_name_used = component_name
                        break
                    except:
                        try:
                            # Try without assembly
                            result = obj.get_component_property(component_name, "enabled", "")
                            enabled = str(result).lower() == "true"
                            component_name_used = component_name
                            break
                        except:
                            continue
                
                if enabled:
                    try:
                        position = obj.get_screen_position()
                        status = f"✅ {obj.name}" if component_name_used else f"✅ {obj.name} (assumed enabled)"
                        print(f"   {status} (ID: {obj.id})")
                        interactable_2d.append({
                            "name": obj.name,
                            "id": obj.id,
                            "collider": collider_type,
                            "position": position
                        })
                    except Exception as e:
                        print(f"   ⚠️  {obj.name} (ID: {obj.id}): Error getting position: {e}")
                else:
                    print(f"   ⏭️  {obj.name} (ID: {obj.id}): Component disabled")
                    
        except Exception as e:
            print(f"   ⚠️  Error searching for {collider_type}: {e}")
    
    # Remove duplicates by ID
    seen_ids = set()
    unique_interactables = []
    for item in interactable_2d:
        if item["id"] not in seen_ids:
            seen_ids.add(item["id"])
            unique_interactables.append(item)
    
    # Print all interactables
    print("\n🎮 Interactable 2D Objects Found:\n")
    for item in unique_interactables:
        x, y = item["position"]
        print(f"- {item['name']} (AltID: {item['id']})")
        print(f"  ↳ Collider: {item['collider']}")
        print(f"  ↳ Screen Position: x={x}, y={y}\n")

    # Print count
    print(f"✅ Total 2D interactable objects: {len(unique_interactables)}")

    return unique_interactables

get_interactable_2d_objects()