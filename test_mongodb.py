from animal_shelter import AnimalShelter


print("Connecting to MongoDB...")

shelter = AnimalShelter()

print("Connected!")

animals = shelter.read({})

print(f"Number of animals found: {len(animals)}")

print("\nFirst 3 records:")
for animal in animals[:3]:
    print(animal)