from openai import OpenAI

"""CVIAS's Vision Language Module (InternVL)."""


import base64
import math
import re
from io import BytesIO

import numpy as np
from cog_cv_abstraction.schema.detected_object import DetectedObject
from PIL import Image


class VisionLanguageModelVLLM:
    def __init__(
        self,
        endpoint: str,
        api_key: str,
        model: str,
        parallel_inference: bool = False,
    ):
        self.client = None
        if not parallel_inference:
            self.client = OpenAI(
                api_key=api_key,
                base_url=endpoint,
            )
        self.parallel_inference = parallel_inference
        self.model_name = model
        self.model = model
        self.endpoint = endpoint
        self.api_key = api_key

    def convert_np_image_to_url(self, image: np.ndarray) -> str:
        """Convert a NumPy image array to a base64-encoded URL."""
        buffered = BytesIO()
        image.save(buffered, format="JPEG")
        image_base64 = base64.b64encode(buffered.getvalue()).decode("utf-8")
        return f"data:image/jpeg;base64,{image_base64}"

    def infer_with_image(
        self,
        language: str,
        image: np.ndarray | None = None,
        image_path: str | None = None,
        max_new_tokens: int = 1024,
        add_generation_prompt: bool = True,
    ) -> str:
        """Perform image inference with given video inputs."""
        assert (  # noqa: S101
            image is not None or image_path is not None
        ), "One of 'image' or 'image_path' must be defined."
        if image_path:
            image = Image.open(image_path).convert("RGB")
        else:
            image = Image.fromarray(image)

        if self.parallel_inference:
            client = OpenAI(
                api_key=self.api_key,
                base_url=self.endpoint,
            )

        else:
            client = self.client.stream

        image_url = self.convert_np_image_to_url(image)

        chat_response = client.chat.completions.create(
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": language},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                }
            ],
            model=self.model,
            max_tokens=5,
            logprobs=True,
        )

        response = chat_response.choices[0].message.content
        bool_response = chat_response.choices[0].logprobs.content[0]
        if bool_response.token in ["Yes", "No"]:
            confidence = math.exp(bool_response.logprob)
        else:
            confidence = 0.0
        return response, confidence

    def detect(
        self,
        frame_img: np.ndarray,
        scene_description: str,
        threshold: float = 0.1,
        confidence_as_token_probability: bool = False,
    ) -> DetectedObject:
        """Detect objects in the given frame image.

        Args:
            frame_img (np.ndarray): The image frame to process.
            scene_description (str): Description of the scene.
            threshold (float): Detection threshold.
            confidence_as_token_probability (bool):
                Whether to use token probability as confidence.

        Returns:
            DetectedObject: Detected objects with their details.
        """
        if confidence_as_token_probability:
            parsing_rule = [
                "You must only return a Yes or No, and not both, to any question asked. "  # noqa: E501
                "You must not include any other symbols, information, text, justification in your answer or repeat Yes or No multiple times.",  # noqa: E501
                "For example, if the question is 'Is there a cat present in the Image?', the answer must only be 'Yes' or 'No'.",  # noqa: E501
            ]
            parsing_rule = "\n".join(parsing_rule)
            prompt = (
                rf"Is there a {scene_description} present in the image? "
                f"[PARSING RULE]\n:{parsing_rule}"
            )

            response, confidence = self.infer_with_image(
                language=prompt, image=frame_img
            )
            # TODO: Add a check for the response to be Yes or NO or clean up response better  # noqa: E501
            if "yes" in response.lower():
                detected = True
                if confidence <= threshold:
                    confidence = 0.0
                    detected = False
                probability = confidence
            else:
                detected = False
            probability = confidence
        else:
            parsing_rule = (
                "You must return a single float confidence value in a scale 0 to 10"
                "For example: 0.1,1.4,2.6,3.7,4.2,5.4,6.2,7.7,8.7,9.8,10.0"
                "Do not add any chatter."
                "Do not say that I cannot determine. Do your best."
            )
            prompt = (
                rf"How confidently can you say that the image describe {scene_description}."  # noqa: E501
                f"[PARSING RULE]\n:{parsing_rule}"
            )
            try:
                confidence_str, _ = self.infer_with_image(
                    language=prompt, image=frame_img
                )
                float_search = re.search(r"\d+(\.\d+)?", confidence_str)
                confidence = (
                    float(float_search.group()) if float_search else 0.10
                )
            except SyntaxError:
                float_search = re.search(r"\d+(\.\d+)?", confidence_str)
                confidence = (
                    float(float_search.group()) if float_search else 0.10
                )
            confidence = confidence * 1 / 10  # scale the confidence to 0-1
            confidence = min(confidence, 1.0)
            probability = confidence
            detected = True
            if confidence <= threshold:
                detected = False

        return DetectedObject(
            name=scene_description,
            model_name=self.model_name,
            confidence=round(confidence, 3),
            probability=round(probability, 3),
            number_of_detection=1,
            is_detected=detected,
        )


if __name__ == "__main__":
    vision_language_model = VisionLanguageModelVLLM(
        endpoint="http://localhost:8000/v1",
        api_key="empty",
        model="OpenGVLab/InternVL2-8B",
    )

    prompt = "Describe this image"

    # * * * Example usage - 2 * * * #
    image_path = "/opt/mars/_dev_/test_data/traffic.png"
    image = Image.open(image_path).convert("RGB")
    obj = vision_language_model.detect(
        frame_img=np.array(image),
        scene_description=prompt,
        threshold=0.1,
        confidence_as_token_probability=False,
    )
    print(obj)
