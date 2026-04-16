import { GoogleGenAI } from "@google/genai";

const ai = new GoogleGenAI({ apiKey: process.env.GEMINI_API_KEY || '' });

export async function generateAIInsight(componentName: string, mismatchScore: number) {
  if (!process.env.GEMINI_API_KEY) {
    return "Detected a structural shift in the component. This affects element accessibility and violates the spatial grid.";
  }

  try {
    const response = await ai.models.generateContent({
      model: "gemini-3-flash-preview",
      contents: `You are an expert UI/UX QA engineer. A visual regression test failed for a component named "${componentName}" with a mismatch score of ${mismatchScore}%. 
    Generate a professional, concise "AI Automated Insight" (2-3 sentences) explaining what might have happened and the impact. 
    Focus on technical terms like "vertical shift", "container narrowing", "spatial grid", "accessibility".`,
    });
    
    return response.text || "Detected a structural shift in the component. This affects element accessibility and violates the spatial grid.";
  } catch (error) {
    console.error("Error generating AI insight:", error);
    return "Detected a structural shift in the component. This affects element accessibility and violates the spatial grid.";
  }
}
