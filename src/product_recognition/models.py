
import torch
import torchvision.models as models
import torchvision.transforms as transforms
from PIL import Image
import numpy as np
import io
from typing import List

# Load ResNet18 model
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
model = None

def load_model():
    global model
    if model is None:
        model = models.resnet18(weights=models.ResNet18_Weights.DEFAULT)
        model = torch.nn.Sequential(*list(model.children())[:-1])
        model.eval()
        model.to(device)
    return model

def get_embedding_from_image(image_bytes: bytes) -> List[float]:
    model = load_model()
    transform = transforms.Compose([
        transforms.Resize((224, 224)),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
    ])
    
    image = Image.open(io.BytesIO(image_bytes)).convert('RGB')
    image_tensor: torch.Tensor = transform(image).unsqueeze(0).to(device)  # type: ignore
    
    with torch.no_grad():
        embedding = model(image_tensor)
    
    return embedding.squeeze().cpu().numpy().tolist()

def warmup_model():
    load_model()
    dummy_image = np.random.randint(0, 255, (224, 224, 3), dtype=np.uint8)
    get_embedding_from_image(dummy_image.tobytes())

