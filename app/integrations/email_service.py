"""
Email service for sending booking confirmations
"""
import aiosmtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from app.config import settings
from typing import Dict, Optional
from datetime import datetime


class EmailService:
    """Handles email sending"""
    
    def __init__(self):
        self.smtp_host = settings.smtp_host
        self.smtp_port = settings.smtp_port
        self.smtp_user = settings.smtp_user
        self.smtp_password = settings.smtp_password
        self.from_email = settings.from_email or settings.smtp_user
    
    async def send_booking_confirmation(
        self,
        to_email: str,
        customer_name: str,
        appointment_time: datetime,
        appointment_type: str = "Free Trial Activation",
        calendar_link: Optional[str] = None
    ) -> Dict[str, any]:
        """
        Send booking confirmation email
        
        Args:
            to_email: Recipient email
            customer_name: Customer name
            appointment_time: Appointment datetime
            appointment_type: Type of appointment
            calendar_link: Google Calendar link (optional)
        
        Returns:
            Dict with send result
        """
        subject = f"Booking Confirmation - {settings.gym_name}"
        
        # Format appointment time
        time_str = appointment_time.strftime("%B %d, %Y at %I:%M %p")
        
        # Create email body
        body = f"""
Hello {customer_name},

Thank you for booking your {appointment_type} at {settings.gym_name}!

Your appointment is scheduled for:
{time_str}

We're excited to welcome you to our gym!

"""
        
        if calendar_link:
            body += f"Add to your calendar: {calendar_link}\n\n"
        
        body += f"""
If you need to reschedule or have any questions, please reply to this email or contact us at:
Phone: {settings.gym_phone}
Email: {settings.gym_email}

We look forward to seeing you!

Best regards,
{settings.gym_name} Team
"""
        
        # Create HTML version
        html_body = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
        .header {{ background-color: #4CAF50; color: white; padding: 20px; text-align: center; }}
        .content {{ padding: 20px; background-color: #f9f9f9; }}
        .appointment {{ background-color: white; padding: 15px; margin: 15px 0; border-left: 4px solid #4CAF50; }}
        .footer {{ text-align: center; padding: 20px; color: #666; font-size: 12px; }}
        .button {{ display: inline-block; padding: 10px 20px; background-color: #4CAF50; color: white; text-decoration: none; border-radius: 5px; margin: 10px 0; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>{settings.gym_name}</h1>
        </div>
        <div class="content">
            <p>Hello {customer_name},</p>
            <p>Thank you for booking your <strong>{appointment_type}</strong> at {settings.gym_name}!</p>
            
            <div class="appointment">
                <h3>Your Appointment Details</h3>
                <p><strong>Date & Time:</strong> {time_str}</p>
                <p><strong>Type:</strong> {appointment_type}</p>
            </div>
            
            <p>We're excited to welcome you to our gym!</p>
            
            {f'<p><a href="{calendar_link}" class="button">Add to Calendar</a></p>' if calendar_link else ''}
            
            <p>If you need to reschedule or have any questions, please contact us:</p>
            <ul>
                <li>Phone: {settings.gym_phone}</li>
                <li>Email: {settings.gym_email}</li>
            </ul>
            
            <p>We look forward to seeing you!</p>
            
            <p>Best regards,<br>{settings.gym_name} Team</p>
        </div>
        <div class="footer">
            <p>This is an automated confirmation email.</p>
        </div>
    </div>
</body>
</html>
"""
        
        return await self.send_email(
            to_email=to_email,
            subject=subject,
            text_body=body,
            html_body=html_body
        )
    
    async def send_email(
        self,
        to_email: str,
        subject: str,
        text_body: str,
        html_body: Optional[str] = None
    ) -> Dict[str, any]:
        """
        Send email
        
        Args:
            to_email: Recipient email
            subject: Email subject
            text_body: Plain text body
            html_body: HTML body (optional)
        
        Returns:
            Dict with send result
        """
        try:
            message = MIMEMultipart("alternative")
            message["From"] = self.from_email
            message["To"] = to_email
            message["Subject"] = subject
            
            # Add text part
            text_part = MIMEText(text_body, "plain")
            message.attach(text_part)
            
            # Add HTML part if provided
            if html_body:
                html_part = MIMEText(html_body, "html")
                message.attach(html_part)
            
            # Send email
            await aiosmtplib.send(
                message,
                hostname=self.smtp_host,
                port=self.smtp_port,
                username=self.smtp_user,
                password=self.smtp_password,
                use_tls=True
            )
            
            return {
                "success": True,
                "message": "Email sent successfully"
            }
        
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

